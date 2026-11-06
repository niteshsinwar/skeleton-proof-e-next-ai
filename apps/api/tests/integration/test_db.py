"""The database itself: migrations up/down, drift, grants, row-level security, dedupe, shared limits (02 §3, §4)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

from skeleton_proof_e_next_ai.persistence import audit_chain
from skeleton_proof_e_next_ai.persistence.db import Database
from skeleton_proof_e_next_ai.persistence.records import record_webhook
from skeleton_proof_e_next_ai.persistence.schema import metadata
from skeleton_proof_e_next_ai.security.rate_limit import Limit, PostgresRateLimiter

pytestmark = [pytest.mark.integration]
API = Path(__file__).resolve().parents[2]


@pytest.fixture
def engine(migrated: str) -> Iterator[Engine]:
    e = create_engine(migrated)
    yield e
    e.dispose()


def test_migrations_go_down_and_up_again_on_a_scratch_database(database_url: str) -> None:
    url = make_url(database_url)
    scratch = f"{url.database}_scratch"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    try:
        cfg = Config(str(API / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", url.set(database=scratch).render_as_string(hide_password=False))
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


def test_schema_module_matches_the_migrated_database(engine: Engine) -> None:
    """Drift check: persistence/schema.py and the migrations describe the same tables (02/D2)."""
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "include_name": lambda n, t, p: t != "schema" or n in ("app", "audit", "jobs", "ai", "eval", "rag"),
            },
        )
        diff = compare_metadata(ctx, metadata)
    assert diff == [], f"schema.py and the migrations disagree: {diff}"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit.events SET actor = 'x'",
        "DELETE FROM audit.events",
        "DELETE FROM app.work_items",
        "UPDATE app.idempotency_keys SET status = 200",
        "UPDATE ai.attempts SET status = 'succeeded'",
        "DELETE FROM ai.attempts",
        "UPDATE ai.attempt_outputs SET raw_text = 'edited'",
        "UPDATE eval.runs SET passed = 0",
        "DELETE FROM eval.results",
        "DELETE FROM app.proposals",
        "UPDATE rag.documents SET title = 'edited'",
        "UPDATE rag.chunks SET text = 'edited'",
    ],
)
def test_the_app_role_cannot_rewrite_history(engine: Engine, statement: str) -> None:
    with engine.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("SET ROLE app_user"))
        conn.execute(text(statement))


def test_app_roles_cannot_bypass_rls_and_own_nothing(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname IN ('app_user', 'app_worker')")
        ).all()
        owned = conn.execute(
            text(
                "SELECT count(*) FROM pg_tables t JOIN pg_roles r ON r.rolname = t.tableowner "
                "WHERE r.rolname IN ('app_user', 'app_worker')"
            )
        ).scalar_one()
    assert sorted(r.rolname for r in rows) == ["app_user", "app_worker"]
    assert not any(r.rolbypassrls or r.rolsuper for r in rows) and owned == 0


def _as_app(engine: Engine, tenant: str | None, sql: str, **params: object) -> list[object]:
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE app_user"))
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant or ""})
        return (
            list(conn.execute(text(sql), params).all())
            if sql.lstrip().upper().startswith("SELECT")
            else (conn.execute(text(sql), params) and [])
        )


def test_rls_is_enabled_and_forced_on_every_tenant_table(engine: Engine) -> None:
    """FORCE only matters for the table owner, which the app never is, so no behaviour test can see it:
    assert it in the catalog (02/Z10; found by the B2 mutation check)."""
    tables = ["work_items", "idempotency_keys", "outbox", "flags", "uploads", "role_grants", "events"]
    tables += ["attempts", "attempt_context", "attempt_requests", "attempt_outputs", "proposals"]
    tables += ["documents", "chunks"]

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname IN ('app', 'audit', 'ai', 'rag') AND c.relname = ANY(:t)"
            ),
            {"t": tables},
        ).all()
    assert sorted(r.relname for r in rows) == sorted(tables)
    assert all(r.relrowsecurity and r.relforcerowsecurity for r in rows), rows


def test_rls_isolates_tenants_and_fails_closed_when_unset(engine: Engine) -> None:
    a, b, item = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000b1", str(uuid.uuid7())
    now = datetime.now(UTC)
    _as_app(
        engine,
        a,
        """INSERT INTO app.work_items (id, tenant_id, title, state, version, created_by, created_at, updated_at)
                          VALUES (:id, :t, 'rls', 'draft', 1, 'x', :now, :now)""",
        id=item,
        t=a,
        now=now,
    )
    count = "SELECT id FROM app.work_items WHERE id = CAST(:id AS uuid)"
    assert len(_as_app(engine, a, count, id=item)) == 1
    assert _as_app(engine, b, count, id=item) == []
    assert _as_app(engine, None, count, id=item) == [], "an unset tenant must see nothing (fail closed)"
    with pytest.raises(ProgrammingError, match="row-level security"):
        _as_app(
            engine,
            b,
            """INSERT INTO app.work_items (id, tenant_id, title, state, version, created_by, created_at, updated_at)
                              VALUES (:id, :t, 'smuggled', 'draft', 1, 'x', :now, :now)""",
            id=str(uuid.uuid7()),
            t=a,
            now=now,
        )


@pytest.mark.anyio
async def test_webhooks_are_deduplicated_by_id(migrated: str) -> None:
    db = Database(migrated, "app_user")
    try:
        async with db.transaction(tenant_id=None, actor="t") as conn:
            assert await record_webhook(conn, "msg_dedupe_1", "stripe") is True
        async with db.transaction(tenant_id=None, actor="t") as conn:
            assert await record_webhook(conn, "msg_dedupe_1", "stripe") is False
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_shared_rate_limit_holds_across_instances(migrated: str) -> None:
    """Two app instances share one Postgres-backed limit (01/AL2): the burst is spent once, not per instance."""
    db1, db2 = Database(migrated, "app_user"), Database(migrated, "app_user")
    try:
        l1, l2 = PostgresRateLimiter(db1.engine, "app_user"), PostgresRateLimiter(db2.engine, "app_user")
        limit, key, now = Limit(per_second=1, burst=2), f"k-{uuid.uuid4()}", datetime.now(UTC)
        results = [
            (await l1.check(key, limit, now)).allowed,
            (await l2.check(key, limit, now)).allowed,
            (await l1.check(key, limit, now)).allowed,
        ]
        assert results == [True, True, False]
    finally:
        await db1.dispose()
        await db2.dispose()


def test_the_audit_chain_head_is_locked_while_a_row_is_linked(engine: Engine) -> None:
    """02/D6: a second writer waits for the first rather than reading the same head and forking the chain."""
    tenant = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(audit_chain.HEAD_INIT), {"t": tenant})
    with engine.connect() as first, engine.connect() as second:
        holding = first.begin()
        first.execute(text(audit_chain.HEAD_LOCK), {"t": tenant})
        with second.begin():
            second.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError, match="lock"):
                second.execute(text(audit_chain.HEAD_LOCK), {"t": tenant})
        holding.rollback()
