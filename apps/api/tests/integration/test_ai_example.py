"""EXAMPLE SLICE: the brief step end to end through HTTP, on real Postgres, with the labelled fake (06/T4).

Replays: a safety check fails open when the provider is unavailable (10 §5 #11): here the brief is refused with 503
and the item is untouched; a fabricated citation is accepted (04 §8); the product is unusable without the AI (01 §5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.config.project import DEFAULT_TENANT, MULTI_TENANT
from skeleton_proof_e_next_ai.intelligence.agents import load_agents
from skeleton_proof_e_next_ai.intelligence.catalogue import load
from skeleton_proof_e_next_ai.intelligence.gateway import Gateway
from skeleton_proof_e_next_ai.intelligence.project_steps import REGISTRY
from skeleton_proof_e_next_ai.intelligence.providers.fake import FakeProvider, Reply
from skeleton_proof_e_next_ai.intelligence.steps import StepRunner

from ..conftest import TENANT_A, auth

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

TENANT = TENANT_A if MULTI_TENANT else str(DEFAULT_TENANT)

AI = Path(__file__).resolve().parents[4] / "ai"
TITLE = "Pay invoice 77 for the warehouse"


def with_fake(app: Any, replies: list[Reply]) -> FakeProvider:
    catalogue = load(AI / "models.yaml", today=date(2026, 11, 5), production=False)
    fake = FakeProvider.scripted("anthropic", replies)
    gateway = Gateway(catalogue, {"anthropic": fake}, sleep=lambda _: _no_wait())
    app.state.core.ai = StepRunner(REGISTRY, load_agents(AI / "agents", catalogue), gateway, lambda: datetime.now(UTC))
    return fake


async def _no_wait() -> None:
    return None


async def _item(client: httpx.AsyncClient, token: str, title: str = TITLE) -> str:
    r = await client.post("/work-items", json={"title": title}, headers=auth(token))
    assert r.status_code == 201
    return str(r.json()["id"])


def _attempts(migrated: str, entity_id: str) -> list[tuple[str, str | None]]:
    engine = create_engine(migrated)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT status, reason FROM ai.attempts WHERE entity_id = :e"), {"e": entity_id}).all()
    engine.dispose()
    return [tuple(r) for r in rows]  # type: ignore[misc]


@pytest.mark.covers("POST /work-items/{item_id}/brief")
async def test_a_verified_brief_comes_back_and_its_attempt_is_recorded(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    app, client = app_and_client
    with_fake(
        app, [Reply.json({"points": [{"text": "It is about invoice 77.", "cite": {"source": "c1", "quote": TITLE}}]})]
    )
    alice = user("alice", ["member"])
    item = await _item(client, alice)
    r = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    assert r.json()["points"][0]["cite"]["quote"] == TITLE
    assert _attempts(migrated, item) == [("succeeded", None)]


MISQUOTED = {"points": [{"text": "Approved by the board.", "cite": {"source": "c1", "quote": "the board approved it"}}]}


@pytest.mark.parametrize(
    ("reply", "status", "reason"),
    [
        (Reply.json(MISQUOTED), "invalid", "citation_not_verbatim"),
        (Reply.json({"points": []}), "abstained", "verifier_abstained"),
    ],
)
async def test_an_unsupported_brief_is_rejected_or_abstains(
    app_and_client: tuple[Any, httpx.AsyncClient],
    user: Callable[..., str],
    migrated: str,
    reply: Reply,
    status: str,
    reason: str,
) -> None:
    app, client = app_and_client
    with_fake(app, [reply])
    alice = user("alice", ["member"])
    item = await _item(client, alice)
    r = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
    assert r.status_code == 200 and r.json()["status"] == status and r.json()["points"] == []
    assert _attempts(migrated, item) == [(status, reason)]


async def test_the_provider_being_down_refuses_the_brief_and_leaves_the_item_working(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    app, client = app_and_client
    with_fake(app, [Reply.down()] * 3)
    alice = user("alice", ["member"])
    item = await _item(client, alice)
    r = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
    assert r.status_code == 503 and r.headers["Retry-After"] == "30"
    assert _attempts(migrated, item) == [("failed", "provider_unavailable")]
    assert (await client.get(f"/work-items/{item}", headers=auth(alice))).status_code == 200  # the product still works


async def test_with_no_key_the_ai_is_off_and_the_product_works(
    client: httpx.AsyncClient, user: Callable[..., str], migrated: str
) -> None:
    alice = user("alice", ["member"])
    item = await _item(client, alice)  # the app started with no provider key: AI is off
    r = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
    assert r.status_code == 503
    assert _attempts(migrated, item) == [("failed", "ai_off")]


async def test_the_steps_kill_switch_refuses_before_any_call(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    app, client = app_and_client
    fake = with_fake(app, [Reply.json({"points": []})])
    alice = user("alice", ["member"])
    item = await _item(client, alice)
    engine = create_engine(migrated)  # set directly: at tier E the admin route needs a second approver (02/Z6)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.flags (tenant_id, key, enabled, updated_by, updated_at, reason) VALUES "
                "(:t, 'ai.work_item_brief', false, 'test', now(), 'testing') ON CONFLICT (tenant_id, key) "
                "DO UPDATE SET enabled = false"
            ),
            {"t": TENANT},
        )
    try:
        r = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
        assert r.status_code == 503 and fake.calls == [] and _attempts(migrated, item) == []
    finally:  # the tenant is shared by every test here: switch the step back on
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM app.flags WHERE tenant_id = :t AND key = 'ai.work_item_brief'"), {"t": TENANT}
            )
        engine.dispose()


async def test_another_persons_item_cannot_be_briefed(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str]
) -> None:
    app, client = app_and_client
    fake = with_fake(app, [])
    item = await _item(client, user("alice", ["member"]))
    r = await client.post(f"/work-items/{item}/brief", headers=auth(user("carol", ["member"])))
    assert r.status_code == 404 and fake.calls == []


GOOD = Reply.json({"points": [{"text": "It is about invoice 77.", "cite": {"source": "c1", "quote": TITLE}}]})


def _while_running(app: Any, meanwhile: Callable[[], Any]) -> None:
    """Runs `meanwhile` after the first step call has its answer but before the route records it (a slow model)."""
    runner, calls = app.state.core.ai, []
    real = runner.run

    async def run(*args: Any, **kwargs: Any) -> Any:
        result = await real(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            await meanwhile()
        return result

    runner.run = run


async def test_a_brief_overtaken_by_a_newer_one_is_refused(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    """Late output from a superseded run is fenced (02/J6): the person asked again and the newer answer landed first."""
    app, client = app_and_client
    with_fake(app, [GOOD, GOOD])
    alice = user("alice", ["member"])
    item = await _item(client, alice)
    newer: list[httpx.Response] = []

    async def ask_again() -> None:
        newer.append(await client.post(f"/work-items/{item}/brief", headers=auth(alice)))

    _while_running(app, ask_again)
    late = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
    assert newer[0].status_code == 200
    assert late.status_code == 409 and late.json()["code"] == "superseded", late.text
    assert len(_attempts(migrated, item)) == 2  # both recorded; only the newer one was used


async def test_a_brief_written_while_its_item_changed_is_refused(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str]
) -> None:
    app, client = app_and_client
    with_fake(app, [GOOD])
    alice = user("alice", ["member"])
    item = await _item(client, alice)

    async def submit() -> None:
        r = await client.post(f"/work-items/{item}/submit", headers=auth(alice, **{"If-Match": '"1"'}))
        assert r.status_code == 200, r.text

    _while_running(app, submit)
    r = await client.post(f"/work-items/{item}/brief", headers=auth(alice))
    assert r.status_code == 409 and r.json()["code"] == "superseded", r.text
