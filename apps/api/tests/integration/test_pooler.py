"""Through a transaction-mode PgBouncer, the app's driver keeps its prepared statements working (01/R7).

psycopg 3 prepares a query once it has run a few times on a connection; in transaction pooling the next transaction
may land on another server connection, where that statement doesn't exist. PgBouncer 1.22 or newer with
`max_prepared_statements` > 0 tracks protocol-level prepared statements and re-prepares them where needed, and
psycopg's docs require libpq 17 or newer on the client for it (or `prepared_max = None`).

Runs only where POOLER_DATABASE_URL points at a PgBouncer (`make test-pooler`, the CI pooler job, ops/pooler/);
REQUIRE_POOLER=1 turns a missing pooler into an error, as REQUIRE_DB does for the database.
"""

from __future__ import annotations

import asyncio
import os
import re

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from skeleton_proof_e_next_ai.persistence.db import Database

POOLER = os.environ.get("POOLER_DATABASE_URL", "")
if not POOLER and os.environ.get("REQUIRE_POOLER") == "1":
    raise pytest.UsageError("REQUIRE_POOLER=1 but POOLER_DATABASE_URL is not set: the pooler lane cannot run.")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POOLER, reason="no POOLER_DATABASE_URL (make test-pooler; the CI pooler job sets it)"),
]

CLIENTS, ROUNDS = 8, 30  # far more client connections than the pooler's server connections (ops/pooler/)


def _libpq_url(database: str | None = None) -> str:
    url = make_url(POOLER).set(drivername="postgresql")
    if database:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


def test_the_pooler_is_pgbouncer_1_22_or_newer() -> None:
    # The admin console speaks only the simple query protocol, so the raw libpq call is used.
    with psycopg.connect(_libpq_url("pgbouncer"), autocommit=True) as conn:
        result = conn.pgconn.exec_(b"SHOW VERSION")
        version = (result.get_value(0, 0) or b"").decode()
    match = re.search(r"PgBouncer (\d+)\.(\d+)", version)
    assert match, f"not a PgBouncer: {version!r}"
    assert (int(match.group(1)), int(match.group(2))) >= (1, 22), f"{version}: prepared statements need 1.22+ (01/R7)"


def test_the_client_libpq_can_deallocate_through_the_pooler() -> None:
    assert psycopg.pq.version() >= 170000, (
        f"libpq {psycopg.pq.version()}: psycopg needs libpq 17+ through PgBouncer, or prepared_max = None (W61)"
    )


@pytest.mark.anyio
async def test_prepared_statements_work_through_transaction_pooling() -> None:
    db = Database(POOLER, app_role=None, pool_size=CLIENTS)
    errors: list[str] = []

    async def client(n: int) -> None:
        for i in range(ROUNDS):
            try:
                async with db.transaction(tenant_id=None, actor=f"client-{n}") as conn:
                    got = (await conn.execute(text("SELECT CAST(:x AS integer) + 1"), {"x": i})).scalar_one()
                    assert got == i + 1
                    # The transaction-local settings the app relies on stay in this transaction.
                    actor = (await conn.execute(text("SELECT current_setting('app.actor')"))).scalar_one()
                    assert actor == f"client-{n}"
            except (DBAPIError, AssertionError) as exc:  # collected, so one failure doesn't hide the others
                errors.append(f"client {n}, round {i}: {type(exc).__name__}: {str(exc).splitlines()[0]}")
            await asyncio.sleep(0)

    try:
        await asyncio.gather(*(client(n) for n in range(CLIENTS)))
        # The statements really were prepared, and by the pooler: it names them PGBOUNCER_<n> on the server.
        async with db.transaction(tenant_id=None, actor="probe") as conn:
            names = (await conn.execute(text("SELECT name FROM pg_prepared_statements"))).scalars().all()
    finally:
        await db.dispose()
    assert not errors, f"{len(errors)} of {CLIENTS * ROUNDS} transactions failed through the pooler: {errors[:3]}"
    assert names, "no prepared statements on the server: the test proved nothing about them"
    assert all(name.startswith("PGBOUNCER_") for name in names), names
