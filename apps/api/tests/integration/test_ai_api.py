"""The generic AI API on real Postgres: status, "why did the assistant say that", feedback and proposals (04/X6,
06/E10, README #9, 02/Z6, 02/A7)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.application import proposals as uc
from skeleton_proof_e_next_ai.config.project import DEFAULT_TENANT, MULTI_TENANT
from skeleton_proof_e_next_ai.domain.ai import Attempt, AttemptStatus, ExecutionMode, Proposal, Usage
from skeleton_proof_e_next_ai.domain.principals import Principal, PrincipalKind
from skeleton_proof_e_next_ai.persistence.ai_records import PgAttemptLog
from skeleton_proof_e_next_ai.persistence.db import Database
from skeleton_proof_e_next_ai.persistence.proposals import PgProposals
from skeleton_proof_e_next_ai.persistence.records import PgAudit

from ..conftest import TENANT_A, auth

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

TENANT = UUID(TENANT_A) if MULTI_TENANT else DEFAULT_TENANT
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class NoteExecutor:
    ran: ClassVar[list[UUID]] = []

    async def precheck(self, p: Proposal, principal: Principal) -> str | None:
        return None

    async def execute(self, p: Proposal, principal: Principal) -> dict[str, Any]:
        NoteExecutor.ran.append(p.id)
        return {"noted_by": principal.subject}


async def _attempt(migrated: str, actor: str) -> UUID:
    db = Database(migrated, "app_user")
    a = Attempt(
        id=uuid.uuid7(), tenant_id=TENANT, step="summary", agent="summary", agent_version=1, agent_hash="a" * 64,
        route="default", mode=ExecutionMode.FIXTURE, status=AttemptStatus.SUCCEEDED, started_at=NOW, finished_at=NOW,
        entity="record", entity_id="1", actor=actor, principal_kind="human", on_behalf_of=None,
        usage=Usage.none_spent(), output_text='{"summary": "ok"}', result={"summary": "ok"},
    )  # fmt: skip
    try:
        async with db.transaction(tenant_id=TENANT, actor=actor) as conn:
            await PgAttemptLog(conn).record(a)
    finally:
        await db.dispose()
    return a.id


async def _proposal(migrated: str) -> UUID:
    db = Database(migrated, "app_user")
    agent = Principal("agent-1", PrincipalKind.AGENT, TENANT, frozenset({"member"}), on_behalf_of="alice")
    try:
        async with db.transaction(tenant_id=TENANT, actor="agent-1") as conn:
            ports = uc.Ports(PgProposals(conn), PgAudit(conn), {"note": NoteExecutor()})
            p = await uc.propose(
                ports, agent, kind="note", payload={"text": "x"}, summary="Add a note.", evidence={}, now=NOW
            )
    finally:
        await db.dispose()
    return p.id


@pytest.mark.covers("GET /ai/status")
async def test_status_shows_whether_ai_is_on(client: httpx.AsyncClient, user: Callable[..., str]) -> None:
    r = await client.get("/ai/status", headers=auth(user("alice", ["member"])))
    # No provider key in tests: the step is switched on but not available, and screens say so (01/R5).
    assert r.status_code == 200 and r.json() == {
        "switched_on": True,
        "steps": [{"name": "work_item_brief", "available": False, "switched_on": True}],
    }


@pytest.mark.covers("GET /ai/attempts/{attempt_id}")
async def test_an_attempt_is_visible_to_its_person_and_inspectors_and_to_nobody_else(
    client: httpx.AsyncClient, user: Callable[..., str], migrated: str
) -> None:
    attempt = await _attempt(migrated, "alice")
    mine = await client.get(f"/ai/attempts/{attempt}", headers=auth(user("alice", ["member"])))
    assert mine.status_code == 200 and mine.json()["said"]["result"] == {"summary": "ok"}
    assert (await client.get(f"/ai/attempts/{attempt}", headers=auth(user("bob", ["approver"])))).status_code == 200
    other = await client.get(f"/ai/attempts/{attempt}", headers=auth(user("carol", ["member"])))
    absent = await client.get(f"/ai/attempts/{uuid.uuid4()}", headers=auth(user("carol", ["member"])))
    assert other.status_code == absent.status_code == 404 and other.json()["code"] == absent.json()["code"]


@pytest.mark.covers("POST /ai/attempts/{attempt_id}/feedback")
async def test_feedback_is_stored_and_audited(
    client: httpx.AsyncClient, user: Callable[..., str], migrated: str
) -> None:
    attempt = await _attempt(migrated, "alice")
    r = await client.post(
        f"/ai/attempts/{attempt}/feedback",
        json={"verdict": "wrong", "correction": "It was rejected."},
        headers=auth(user("alice", ["member"])),
    )
    assert r.status_code == 204
    engine = create_engine(migrated)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT verdict, correction FROM ai.feedback WHERE attempt_id = :a"), {"a": attempt}
        ).one()
        audited = conn.execute(text("SELECT count(*) FROM audit.events WHERE action = 'ai.feedback'")).scalar_one()
    engine.dispose()
    assert tuple(row) == ("wrong", "It was rejected.") and audited >= 1


@pytest.mark.covers("GET /proposals")
@pytest.mark.covers("GET /proposals/{proposal_id}")
@pytest.mark.covers("POST /proposals/{proposal_id}/approve")
async def test_an_approved_proposal_runs_once_as_its_approver(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    app, client = app_and_client
    app.state.core.ai_executors = {"note": lambda conn: NoteExecutor()}
    pid = await _proposal(migrated)
    bob = user("bob", ["approver"])
    listed = await client.get("/proposals", headers=auth(bob))
    assert pid in [UUID(p["id"]) for p in listed.json()["items"]]
    alice = user("alice", ["approver"])  # the person it was proposed for: may not decide it
    assert (
        await client.post(f"/proposals/{pid}/approve", json={}, headers=auth(alice, **{"If-Match": '"1"'}))
    ).status_code == 403
    without_version = await client.post(f"/proposals/{pid}/approve", json={}, headers=auth(bob))
    assert without_version.status_code == 428
    done = await client.post(f"/proposals/{pid}/approve", json={}, headers=auth(bob, **{"If-Match": '"1"'}))
    assert (
        done.status_code == 200
        and done.json()["status"] == "executed"
        and done.json()["outcome"] == {"noted_by": "bob"}
    )
    assert NoteExecutor.ran.count(pid) == 1
    again = await client.post(f"/proposals/{pid}/approve", json={}, headers=auth(bob, **{"If-Match": '"3"'}))
    assert again.status_code == 409 and NoteExecutor.ran.count(pid) == 1
    assert (await client.get(f"/proposals/{pid}", headers=auth(user("carol", ["member"])))).status_code == 404


@pytest.mark.covers("POST /proposals/{proposal_id}/reject")
async def test_a_rejection_needs_a_reason_and_never_runs(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    app, client = app_and_client
    app.state.core.ai_executors = {"note": lambda conn: NoteExecutor()}
    pid = await _proposal(migrated)
    bob = user("bob", ["approver"])
    assert (
        await client.post(f"/proposals/{pid}/reject", json={}, headers=auth(bob, **{"If-Match": '"1"'}))
    ).status_code == 422
    r = await client.post(
        f"/proposals/{pid}/reject", json={"reason": "Not needed."}, headers=auth(bob, **{"If-Match": '"1"'})
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected" and pid not in NoteExecutor.ran
