"""The example slice and platform routes end to end on real Postgres, as the app role (02 §2, §4, 05/SG6, SG11)."""

from __future__ import annotations

import ast
import base64
import importlib.util
import time
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import anyio
import httpx
import psycopg
import pytest
from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.api.app import create_app
from skeleton_proof_e_next_ai.integrations.webhooks.verify import sign

from ..conftest import TENANT_A, TENANT_B, auth, settings_for

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def alice(user: Callable[..., str]) -> str:
    return user("alice", ["member"])


@pytest.fixture
def bob(user: Callable[..., str]) -> str:
    return user("bob", ["approver"])


async def _create(client: httpx.AsyncClient, token: str, title: str = "Fix the gate") -> dict[str, Any]:
    r = await client.post("/work-items", json={"title": title}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.covers("POST /work-items")
async def test_create_returns_201_with_an_etag_and_writes_audit_and_outbox(
    client: httpx.AsyncClient, alice: str, migrated: str
) -> None:
    r = await client.post("/work-items", json={"title": "Fix the gate"}, headers=auth(alice))
    assert r.status_code == 201 and r.headers["etag"] == '"1"'
    item_id = r.json()["id"]
    engine = create_engine(migrated)
    with engine.connect() as conn:
        audit = conn.execute(
            text("SELECT action, actor, principal_kind FROM audit.events WHERE entity_id = :i"), {"i": item_id}
        ).all()
        events = conn.execute(
            text("SELECT kind, sequence FROM app.outbox WHERE aggregate_id = :i"), {"i": item_id}
        ).all()
    engine.dispose()
    assert [tuple(a) for a in audit] == [("work_item.created", "alice", "human")]
    assert [tuple(e) for e in events] == [("work_item.created", 1)]


async def test_retried_create_replays_and_a_reused_key_with_another_body_is_refused(
    client: httpx.AsyncClient, alice: str
) -> None:
    headers = auth(alice)
    first = await client.post("/work-items", json={"title": "Once"}, headers=headers)
    again = await client.post("/work-items", json={"title": "Once"}, headers=headers)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    other = await client.post("/work-items", json={"title": "Different"}, headers=headers)
    assert other.status_code == 422 and other.json()["code"] == "idempotency-key-reused"


async def test_a_side_effecting_post_needs_an_idempotency_key(client: httpx.AsyncClient, alice: str) -> None:
    r = await client.post("/work-items", json={"title": "x"}, headers={"Authorization": f"Bearer {alice}"})
    assert r.status_code == 400 and r.json()["code"] == "idempotency-key-required"


async def test_unknown_fields_are_rejected(client: httpx.AsyncClient, alice: str) -> None:
    r = await client.post("/work-items", json={"title": "x", "state": "approved"}, headers=auth(alice))
    assert r.status_code == 422  # no mass assignment (02/A8)


@pytest.mark.covers("GET /work-items/{item_id}")
async def test_bola_another_users_item_is_404_with_the_same_body(
    client: httpx.AsyncClient, alice: str, user: Callable[..., str]
) -> None:
    item = await _create(client, alice)
    carol = user("carol", ["member"])
    theirs = await client.get(f"/work-items/{item['id']}", headers=auth(carol))
    absent = await client.get(f"/work-items/{uuid.uuid7()}", headers=auth(carol))
    assert theirs.status_code == absent.status_code == 404
    strip = lambda r: {k: v for k, v in r.json().items() if k not in ("instance", "correlation_id")}  # noqa: E731
    assert strip(theirs) == strip(absent)
    mine = await client.get(f"/work-items/{item['id']}", headers=auth(alice))
    assert mine.status_code == 200 and mine.headers["etag"] == '"1"'


@pytest.mark.covers("POST /work-items/{item_id}/submit")
@pytest.mark.covers("POST /work-items/{item_id}/approve")
async def test_submit_and_approve_need_if_match_and_respect_separation_of_duties(
    client: httpx.AsyncClient, alice: str, bob: str, user: Callable[..., str]
) -> None:
    item = await _create(client, alice)
    url = f"/work-items/{item['id']}"
    assert (await client.post(f"{url}/submit", headers=auth(alice))).status_code == 428
    assert (await client.post(f"{url}/submit", headers=auth(alice, **{"If-Match": '"7"'}))).status_code == 412
    submitted = await client.post(f"{url}/submit", headers=auth(alice, **{"If-Match": '"1"'}))
    assert submitted.status_code == 200 and submitted.json()["state"] == "submitted"
    alice_approver = user("alice", ["approver", "member"])
    own = await client.post(f"{url}/approve", json={}, headers=auth(alice_approver, **{"If-Match": '"2"'}))
    assert own.status_code == 403  # the submitter can't decide their own item (02/Z6)
    agent = user("bob", ["approver"], act="review-bot", scope="work_item.decide")
    assert (await client.post(f"{url}/approve", json={}, headers=auth(agent, **{"If-Match": '"2"'}))).status_code == 403
    approved = await client.post(f"{url}/approve", json={}, headers=auth(bob, **{"If-Match": '"2"'}))
    assert approved.status_code == 200 and approved.json()["decided_by"] == "bob"


@pytest.mark.covers("POST /work-items/{item_id}/reject")
async def test_illegal_transition_lists_the_legal_ones(client: httpx.AsyncClient, alice: str, bob: str) -> None:
    item = await _create(client, alice)
    r = await client.post(
        f"/work-items/{item['id']}/reject", json={"reason": "no"}, headers=auth(bob, **{"If-Match": '"1"'})
    )
    assert r.status_code == 409 and r.json()["legal_transitions"] == ["submit"]


@pytest.mark.covers("GET /work-items")
async def test_list_pages_with_an_opaque_cursor_and_only_shows_my_items(
    client: httpx.AsyncClient, user: Callable[..., str]
) -> None:
    dana, erin = user("dana", ["member"]), user("erin", ["member"])
    mine = [(await _create(client, dana, f"d{i}"))["id"] for i in range(3)]
    await _create(client, erin, "not dana's")
    first = (await client.get("/work-items?limit=2", headers=auth(dana))).json()
    second = (await client.get(f"/work-items?limit=2&cursor={first['next_cursor']}", headers=auth(dana))).json()
    assert [i["id"] for i in first["items"] + second["items"]] == mine and second["next_cursor"] is None
    assert (await client.get("/work-items?cursor=garbage", headers=auth(dana))).status_code == 422


@pytest.mark.covers("POST /admin/flags/{key}/set")
@pytest.mark.covers("POST /admin/changes/{change_id}/approve")
@pytest.mark.covers("POST /admin/changes/{change_id}/reject")
async def test_kill_switch_turns_the_feature_off_and_is_audited(
    client: httpx.AsyncClient, alice: str, user: Callable[..., str], migrated: str
) -> None:
    admin = user("root", ["admin"])
    assert (
        await client.post(
            "/admin/flags/work_items/set", json={"enabled": False, "reason": "incident 42"}, headers=auth(alice)
        )
    ).status_code == 403
    second = user("sam", ["admin"])
    off = await client.post(
        "/admin/flags/work_items/set", json={"enabled": False, "reason": "incident 42"}, headers=auth(admin)
    )
    assert off.status_code == 202  # proposed, not applied: dual authorisation at tier E (02/Z6)
    change = off.json()["change_id"]
    assert (await client.post("/work-items", json={"title": "x"}, headers=auth(alice))).status_code == 201
    decision = {"reason": "agreed"}
    mine = await client.post(f"/admin/changes/{change}/approve", json=decision, headers=auth(admin))
    assert mine.status_code == 403  # the proposer can't approve their own change
    approved = await client.post(f"/admin/changes/{change}/approve", json=decision, headers=auth(second))
    assert approved.status_code == 204, approved.text
    again = await client.post(f"/admin/changes/{change}/reject", json=decision, headers=auth(second))
    assert again.status_code == 422  # a decided change is final
    blocked = await client.post("/work-items", json={"title": "x"}, headers=auth(alice))
    assert blocked.status_code == 503 and blocked.json()["code"] == "feature-disabled"
    back = await client.post(
        "/admin/flags/work_items/set", json={"enabled": True, "reason": "resolved"}, headers=auth(admin)
    )
    on = back.json()["change_id"]
    assert (await client.post(f"/admin/changes/{on}/approve", json=decision, headers=auth(second))).status_code == 204
    assert (await client.post("/work-items", json={"title": "x"}, headers=auth(alice))).status_code == 201
    engine = create_engine(migrated)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM audit.events WHERE action = 'flag.set'")).scalar_one()
    engine.dispose()
    assert n >= 2


@pytest.mark.covers("POST /uploads")
async def test_uploads_are_validated_capped_and_stored_under_server_names(
    client: httpx.AsyncClient, alice: str, app_and_client: Any
) -> None:
    ok = await client.post("/uploads", content=PNG, headers=auth(alice, **{"Content-Type": "image/png"}))
    assert ok.status_code == 201, ok.text
    stored = list(app_and_client[0].state.core.settings.upload_dir.iterdir())
    assert [p.name for p in stored] == [f"{ok.json()['id']}.png"] and oct(stored[0].stat().st_mode)[-3:] == "600"
    lying = await client.post("/uploads", content=b"%PDF-1.7", headers=auth(alice, **{"Content-Type": "image/png"}))
    assert lying.status_code == 415
    big = await client.post(
        "/uploads", content=PNG + b"\x00" * (6 * 1024 * 1024), headers=auth(alice, **{"Content-Type": "image/png"})
    )
    assert big.status_code == 413


@pytest.mark.covers("GET /ready")
async def test_ready_checks_db_migration_head_and_config(client: httpx.AsyncClient) -> None:
    r = await client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json()["checks"] == {"database": "ok", "migration": "ok", "business_config": "ok"}


async def test_another_tenant_cannot_see_my_items(client: httpx.AsyncClient, user: Callable[..., str]) -> None:
    mine = await _create(client, user("frank", ["member"], tenant=TENANT_A))
    intruder = user("frank", ["approver"], tenant=TENANT_B)  # same name, other tenant
    assert (await client.get(f"/work-items/{mine['id']}", headers=auth(intruder))).status_code == 404
    listed = (await client.get("/work-items", headers=auth(intruder))).json()["items"]
    assert mine["id"] not in [i["id"] for i in listed]


async def test_a_privileged_act_needs_a_recent_passkey_sign_in(
    client: httpx.AsyncClient, user: Callable[..., str]
) -> None:
    """02/Z3, Z4 at tier E: a password-only or stale sign-in can't approve; the answer asks for a fresh sign-in."""
    item = await _create(client, user("jo", ["member"]), "Needs approval")
    url = f"/work-items/{item['id']}"
    submitted = await client.post(f"{url}/submit", headers=auth(user("jo", ["member"]), **{"If-Match": '"1"'}))
    assert submitted.status_code == 200, submitted.text
    password_only = user("kim", ["approver"], amr=["pwd"])
    r = await client.post(f"{url}/approve", json={}, headers=auth(password_only, **{"If-Match": '"2"'}))
    assert r.status_code == 403 and r.json()["code"] == "step-up-required", r.text
    fresh = user("kim", ["approver"])
    approved = await client.post(f"{url}/approve", json={}, headers=auth(fresh, **{"If-Match": '"2"'}))
    assert approved.status_code == 200, approved.text


def _verifier() -> Any:
    """Load scripts/verify_audit_chain.py by path: it is an operator script, not part of the package."""
    path = Path(__file__).resolve().parents[4] / "scripts" / "verify_audit_chain.py"
    spec = importlib.util.spec_from_file_location("verify_audit_chain", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_audit_chain_verifies_and_an_edited_row_breaks_it(
    client: httpx.AsyncClient, user: Callable[..., str], migrated: str
) -> None:
    """02/D6 at tier E: rows written by real requests, two at once, form an intact chain; editing one is caught."""
    lee = user("lee", ["member"])
    async with anyio.create_task_group() as tg:  # two writers at once must not fork the chain
        for title in ("first", "second"):
            tg.start_soon(_create, client, lee, title)
    verifier = _verifier()
    dsn = migrated.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        examined, problems = verifier.verify(conn)
    assert examined >= 2 and problems == [], problems
    with psycopg.connect(dsn, autocommit=True) as conn:  # the owner edits history behind the app's back
        conn.execute(
            "UPDATE audit.events SET reason = 'forged' WHERE actor = 'lee' "
            "AND sequence = (SELECT max(sequence) FROM audit.events WHERE actor = 'lee')"
        )
        _, problems = verifier.verify(conn)
    assert any("edited" in p for p in problems), problems


def test_the_audit_verifier_imports_nothing_from_the_app() -> None:
    """An independent verifier shares no code with the writer, or a writer bug could vouch for itself (02/D6)."""
    tree = ast.parse((Path(__file__).resolve().parents[4] / "scripts" / "verify_audit_chain.py").read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported, "the scan found no imports"
    allowed = {"__future__", "argparse", "datetime", "hashlib", "json", "os", "sys", "typing", "psycopg"}
    assert imported <= allowed, imported - allowed


@pytest.mark.covers("POST /admin/roles/{subject}/grant")
@pytest.mark.covers("POST /admin/roles/{subject}/revoke")
async def test_roles_live_in_the_api_and_removing_one_works_on_the_next_call(
    client: httpx.AsyncClient, user: Callable[..., str], migrated: str
) -> None:
    """02/Z4, Z5, Z6: an admin grants and revokes, never for themselves; the change applies on the very next call,
    without waiting for anyone's token to expire; a role claim inside a token grants nothing."""
    admin, gina = user("root", ["admin"]), user("gina", [])
    body = {"role": "approver", "reason": "covering the queue"}
    pending = (await client.get("/work-items", headers=auth(gina))).status_code
    assert pending == 200  # anyone signed in may list their own items
    assert (await client.post("/admin/roles/gina/grant", json=body, headers=auth(gina))).status_code == 403
    assert (await client.post("/admin/roles/root/grant", json=body, headers=auth(admin))).status_code == 403
    unknown = await client.post("/admin/roles/gina/grant", json={**body, "role": "superuser"}, headers=auth(admin))
    assert unknown.status_code == 422
    assert (await client.post("/admin/roles/gina/grant", json=body, headers=auth(admin))).status_code == 204
    item = await _create(client, user("hal", ["member"]), "Needs a decision")
    submit = await client.post(
        f"/work-items/{item['id']}/submit", headers=auth(user("hal", ["member"]), **{"If-Match": '"1"'})
    )
    assert submit.status_code == 200, submit.text
    assert (await client.get(f"/work-items/{item['id']}", headers=auth(gina))).status_code == 200  # approver sees all
    assert (await client.post("/admin/roles/gina/revoke", json=body, headers=auth(admin))).status_code == 204
    assert (await client.get(f"/work-items/{item['id']}", headers=auth(gina))).status_code == 404  # same token, gone
    sql = "SELECT action FROM audit.events WHERE entity = 'role_grant' AND entity_id = 'gina:approver' ORDER BY at"
    engine = create_engine(migrated)
    with engine.connect() as conn:
        actions = conn.execute(text(sql)).scalars().all()
    engine.dispose()
    assert list(actions) == ["role.granted", "role.revoked"]


async def test_a_role_claim_in_the_token_grants_nothing(
    client: httpx.AsyncClient, make_token: Callable[..., str], alice: str
) -> None:
    item = await _create(client, alice, "Mine")
    forged = make_token("ivan", roles=["approver", "admin"])  # the claim is ignored; ivan was never granted a role
    assert (await client.get(f"/work-items/{item['id']}", headers=auth(forged))).status_code == 404


class _BrokenLimiter:
    async def check(self, key: str, limit: Any, now: Any) -> Any:
        raise ConnectionError("the limiter's store is down")


async def test_a_down_limiter_store_fails_writes_closed_and_reads_open(
    app_and_client: tuple[Any, httpx.AsyncClient], alice: str
) -> None:
    """01/R2: the limiter's store failing is a decided case per class, written in FAIL_CLOSED, never an accident."""
    app, client = app_and_client
    app.state.core.limiter = _BrokenLimiter()
    write = await client.post("/work-items", json={"title": "While the limiter is down"}, headers=auth(alice))
    assert write.status_code == 503 and write.json()["code"] == "rate-limiter-unavailable"
    assert write.headers["retry-after"] == "5"
    read = await client.get("/work-items", headers=auth(alice))
    assert read.status_code == 200  # reads stay open, as FAIL_CLOSED says


@pytest.mark.covers("GET /me")
async def test_me_says_who_the_caller_is_and_what_the_grants_allow(
    client: httpx.AsyncClient, user: Callable[..., str], make_token: Callable[..., str]
) -> None:
    """Screens ask the API what the caller may do, so they offer only what will be allowed (03/F9: an affordance;
    the API still authorises every action). Roles come from the grants on this call, never from the token (02/Z5)."""
    me = await client.get("/me", headers=auth(user("judy", ["approver"], name="Judy Hopps")))
    assert me.status_code == 200, me.text
    body = me.json()
    assert (body["subject"], body["name"], body["kind"], body["roles"]) == ("judy", "Judy Hopps", "human", ["approver"])
    assert "work_item.decide" in body["capabilities"] and "roles.manage" not in body["capabilities"]
    forged = await client.get("/me", headers=auth(make_token("kurt", roles=["admin"])))
    assert forged.json()["roles"] == [] and forged.json()["capabilities"] == []
    assert (await client.get("/me")).status_code == 401


async def test_items_carry_the_names_people_had_when_they_acted(
    client: httpx.AsyncClient, user: Callable[..., str]
) -> None:
    """Screens show names, never subjects (03/F16): an item records its creator's and decider's display names."""
    kim = user("kim", ["member"], name="Kim Lee")
    item = await _create(client, kim, "Named")
    assert (item["created_by"], item["created_by_name"], item["decided_by_name"]) == ("kim", "Kim Lee", None)
    submit = await client.post(f"/work-items/{item['id']}/submit", headers=auth(kim, **{"If-Match": '"1"'}))
    assert submit.status_code == 200, submit.text
    lou = user("lou", ["approver"], name="Lou Park")
    approved = await client.post(f"/work-items/{item['id']}/approve", json={}, headers=auth(lou, **{"If-Match": '"2"'}))
    assert approved.status_code == 200, approved.text
    assert approved.json()["decided_by_name"] == "Lou Park"
    nameless = await _create(client, user("max", ["member"]), "No name in the token")
    assert nameless["created_by_name"] is None  # null, never the subject in its place


@pytest.mark.covers("POST /session/revoke")
async def test_a_revoked_token_stops_working_at_once_and_other_sessions_continue(
    client: httpx.AsyncClient, user: Callable[..., str], migrated: str
) -> None:
    """Logout revokes immediately (02/Z4, 03/F40), not when the token happens to expire."""
    token, other = user("alice", ["member"], jti="session-1"), user("alice", ["member"], jti="session-2")
    assert (await client.get("/work-items", headers=auth(token))).status_code == 200
    r = await client.post("/session/revoke", headers=auth(token))
    assert r.status_code == 204, r.text
    after = await client.get("/work-items", headers=auth(token))
    assert after.status_code == 401 and after.json()["code"] == "session-revoked", after.text
    assert (await client.post("/session/revoke", headers=auth(token))).status_code == 401
    assert (await client.get("/work-items", headers=auth(other))).status_code == 200  # only that session ends
    engine = create_engine(migrated)
    with engine.connect() as conn:
        audited = conn.execute(
            text("SELECT count(*) FROM audit.events WHERE action = 'session.revoked' AND actor = 'alice'")
        ).scalar_one()
    engine.dispose()
    assert audited == 1


WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"integration-secret-32-bytes-long").decode()


@pytest.fixture
async def webhook_client(tmp_path: Path, jwks_file: Path, migrated: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for(tmp_path, jwks_file, migrated, webhook_secrets={"billing": [WEBHOOK_SECRET]}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await app.state.core.db.dispose()


def _delivery(webhook_id: str, body: bytes, at: int | None = None) -> dict[str, str]:
    ts = at if at is not None else int(time.time())
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": sign(WEBHOOK_SECRET, webhook_id, ts, body),
    }


@pytest.mark.covers("POST /webhooks/{source}")
async def test_a_webhook_is_verified_queued_once_and_replays_do_nothing(
    webhook_client: httpx.AsyncClient, migrated: str
) -> None:
    """02/I4: signature over the raw body, a timestamp window, dedupe on the id, queue and acknowledge."""
    body = b'{"event": "invoice.paid"}'
    first = await webhook_client.post("/webhooks/billing", content=body, headers=_delivery("msg_1", body))
    assert first.status_code == 202 and first.json() == {"id": "msg_1", "duplicate": False}, first.text
    again = await webhook_client.post("/webhooks/billing", content=body, headers=_delivery("msg_1", body))
    assert again.status_code == 200 and again.json()["duplicate"] is True
    tampered = await webhook_client.post("/webhooks/billing", content=body + b" ", headers=_delivery("msg_2", body))
    assert tampered.status_code == 401
    stale = await webhook_client.post(
        "/webhooks/billing", content=body, headers=_delivery("msg_3", body, at=int(time.time()) - 3600)
    )
    assert stale.status_code == 401
    assert (
        await webhook_client.post("/webhooks/unknown", content=body, headers=_delivery("msg_4", body))
    ).status_code == 404
    engine = create_engine(migrated)
    with engine.connect() as conn:
        jobs = conn.execute(text("SELECT count(*) FROM jobs.jobs WHERE kind = 'webhook.received'")).scalar_one()
    engine.dispose()
    assert jobs == 1
