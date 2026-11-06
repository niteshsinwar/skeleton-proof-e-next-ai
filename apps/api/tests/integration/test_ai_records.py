"""The AI attempt log and admission on real Postgres, as the app role (04/X6, 01/R2, 05/SG11, 06/T4)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from skeleton_proof_e_next_ai.application import ai_runs
from skeleton_proof_e_next_ai.domain.ai import (
    AIBudgetSpent,
    AIUnavailable,
    Attempt,
    AttemptStatus,
    ContextItem,
    ExecutionMode,
    LedgerEntry,
    Trust,
    Usage,
    kill_switch,
)
from skeleton_proof_e_next_ai.domain.principals import Principal, PrincipalKind
from skeleton_proof_e_next_ai.persistence.ai_records import PgAttemptLog
from skeleton_proof_e_next_ai.persistence.db import Database
from skeleton_proof_e_next_ai.persistence.records import PgFlags

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def attempt(tenant: uuid.UUID, **changes: Any) -> Attempt:
    shown = ContextItem("record.details", "record:1", "The invoice was approved.", Trust.RECORD, tenant)
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "tenant_id": tenant,
        "step": "summary",
        "agent": "summary",
        "agent_version": 1,
        "agent_hash": "a" * 64,
        "route": "default",
        "mode": ExecutionMode.LIVE,
        "status": AttemptStatus.SUCCEEDED,
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=2),
        "entity": "record",
        "entity_id": "1",
        "actor": "alice",
        "principal_kind": "human",
        "on_behalf_of": None,
        "provider": "anthropic",
        "requested_model": "claude-opus-5-5",
        "served_model": "claude-opus-5-5",
        "usage": Usage(10, 20, 0, 0, Decimal("0.000440"), "test-2026-11-01"),
        "ledger": (
            LedgerEntry("c1", shown, True, None, 7),
            LedgerEntry("c2", shown, False, "over_token_budget", 7),
        ),
        "request": {"system_sha256": "b" * 64, "user": "Summarise."},
        "output_text": '{"summary": "Approved."}',
        "result": {"summary": "Approved."},
    }
    return Attempt(**(values | changes))


def principal(tenant: uuid.UUID) -> Principal:
    return Principal(subject="alice", kind=PrincipalKind.HUMAN, tenant_id=tenant, roles=frozenset({"member"}))


async def test_an_attempt_is_recorded_whole_and_read_back(migrated: str) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    try:
        a = attempt(tenant)
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            await PgAttemptLog(conn).record(a)
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:

            async def one(sql: str) -> Any:
                return (await conn.execute(text(sql), {"i": a.id})).one()

            row = await one("SELECT status, cost_usd, served_model FROM ai.attempts WHERE id = :i")
            shown = await one(
                "SELECT count(*), count(*) FILTER (WHERE included) FROM ai.attempt_context WHERE attempt_id = :i"
            )
            said = await one("SELECT raw_text, byte_length FROM ai.attempt_outputs WHERE attempt_id = :i")
            (asked,) = await one("SELECT kind FROM ai.attempt_requests WHERE attempt_id = :i")
        assert (row.status, row.cost_usd, row.served_model) == ("succeeded", Decimal("0.000440"), "claude-opus-5-5")
        assert tuple(shown) == (2, 1)
        assert (said.raw_text, said.byte_length, asked) == ('{"summary": "Approved."}', 24, "model_call")
    finally:
        await db.dispose()


async def test_a_failed_attempt_is_recorded_too(migrated: str) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    try:
        a = attempt(
            tenant,
            status=AttemptStatus.FAILED,
            reason="provider_unavailable",
            result=None,
            output_text=None,
            usage=Usage(),
        )
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            await PgAttemptLog(conn).record(a)
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            status = (
                await conn.execute(text("SELECT status FROM ai.attempts WHERE id = :i"), {"i": a.id})
            ).scalar_one()
        assert status == "failed"
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    ("column", "value"),
    [("abstention", None), ("cost_usd", "0.5")],  # an abstention without its words; a non-live attempt that cost money
)
async def test_the_database_refuses_a_record_the_domain_would_refuse(
    migrated: str, column: str, value: str | None
) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    status, mode = ("abstained", "fixture") if column == "abstention" else ("failed", "fixture")
    try:
        with pytest.raises(IntegrityError, match="ck_attempts_"):
            async with db.transaction(tenant_id=tenant, actor="alice") as conn:
                await conn.execute(
                    text(
                        "INSERT INTO ai.attempts (id, tenant_id, step, agent, agent_version, agent_hash, route, mode, "
                        "status, reason, abstention, started_at, finished_at, entity, entity_id, actor, "
                        "principal_kind, cost_usd, signals, correlation_id) VALUES "
                        "(:id, :t, 's', 'a', 1, :h, 'default', :mode, :status, 'x', NULL, now(), now(), 'e', '1', "
                        "'alice', 'human', :cost, '[]', 'c')"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "t": tenant,
                        "h": "a" * 64,
                        "mode": mode,
                        "status": status,
                        "cost": value if column == "cost_usd" else None,
                    },
                )
    finally:
        await db.dispose()


async def test_spend_counts_only_live_attempts_since_the_start_of_the_day(migrated: str) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    try:
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            log = PgAttemptLog(conn)
            await log.record(attempt(tenant))
            await log.record(attempt(tenant, mode=ExecutionMode.FIXTURE, usage=Usage.none_spent()))
            await log.record(attempt(tenant, started_at=NOW - timedelta(days=1), finished_at=NOW - timedelta(days=1)))
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            spent = await PgAttemptLog(conn).spent_since(tenant, NOW.replace(hour=0))
        assert spent == Decimal("0.000440")
    finally:
        await db.dispose()


async def test_admission_honours_both_kill_switches_and_the_daily_budget(migrated: str) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    try:
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            ports = ai_runs.Ports(attempts=PgAttemptLog(conn), flags=PgFlags(conn))
            await ai_runs.admit(
                ports, principal(tenant), "summary", daily_cap_usd=Decimal("1"), now=NOW
            )  # nothing set: on
            await PgFlags(conn).set(kill_switch("summary"), tenant, False, "admin", "testing the switch")
            with pytest.raises(AIUnavailable):
                await ai_runs.admit(ports, principal(tenant), "summary", daily_cap_usd=Decimal("1"), now=NOW)
            await ai_runs.admit(
                ports, principal(tenant), "other", daily_cap_usd=Decimal("1"), now=NOW
            )  # only that step
            with pytest.raises(AIBudgetSpent) as spent:
                await PgAttemptLog(conn).record(attempt(tenant))
                await ai_runs.admit(ports, principal(tenant), "other", daily_cap_usd=Decimal("0.0001"), now=NOW)
            assert spent.value.retry_after == 12 * 3600  # until midnight UTC
    finally:
        await db.dispose()


async def test_a_late_run_sees_the_newer_one_even_when_they_finish_together(migrated: str) -> None:
    """02/J6: recording serialises per subject, so the older run waits for the newer one and then sees it."""
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    older = attempt(tenant)
    newer = attempt(tenant, started_at=NOW + timedelta(seconds=1), finished_at=NOW + timedelta(seconds=2))
    other_item = attempt(
        tenant, entity_id="2", started_at=NOW + timedelta(seconds=5), finished_at=NOW + timedelta(seconds=9)
    )

    async def record_older() -> bool:
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            await PgAttemptLog(conn).record(older)
            return await PgAttemptLog(conn).superseded(older)

    try:
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            await PgAttemptLog(conn).record(other_item)
        async with db.transaction(tenant_id=tenant, actor="alice") as conn:
            await PgAttemptLog(conn).record(newer)
            assert not await PgAttemptLog(conn).superseded(newer)
            late = asyncio.create_task(record_older())
            await asyncio.sleep(0.3)
            assert not late.done(), "the older run recorded while the newer one was still open: there is no fence"
        assert await late, "the older run did not see the newer one"
    finally:
        await db.dispose()
