"""Proposals and LangGraph checkpoints on real Postgres, as the app role (README #9, 04/G6, 13/SK5, 02/D2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from skeleton_proof_e_next_ai.domain.ai import Proposal, ProposalStatus
from skeleton_proof_e_next_ai.intelligence.graphs.approval import LangGraphApprovalWorkflow
from skeleton_proof_e_next_ai.intelligence.graphs.checkpoints import (
    LIBRARY_MIGRATIONS,
    libpq_url,
    open_checkpointer,
)
from skeleton_proof_e_next_ai.persistence.db import Database
from skeleton_proof_e_next_ai.persistence.proposals import PgProposals

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def proposal(tenant: UUID) -> Proposal:
    return Proposal(
        uuid.uuid7(),
        tenant,
        "note",
        {"text": "x"},
        "Add a note.",
        {"attempt": "a1"},
        "agent-1",
        "alice",
        ProposalStatus.PROPOSED,
        1,
        NOW,
    )


async def test_a_proposal_moves_by_version_and_reads_back_whole(migrated: str) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    try:
        p = proposal(tenant)
        async with db.transaction(tenant_id=tenant, actor="agent-1") as conn:
            await PgProposals(conn).add(p)
        decided = p.decide(approve=True, by="bob", reason=None, now=NOW)
        async with db.transaction(tenant_id=tenant, actor="bob") as conn:
            store = PgProposals(conn)
            assert await store.save(decided, 1) is True
            assert await store.save(decided, 1) is False  # a stale version never overwrites
            back = await store.get(p.id)
            open_now = await store.list_open(limit=10)
        assert back == decided and open_now == []
    finally:
        await db.dispose()


async def test_the_database_refuses_a_rejection_without_a_reason(migrated: str) -> None:
    db, tenant = Database(migrated, "app_user"), uuid.uuid4()
    try:
        with pytest.raises(IntegrityError, match="ck_proposals_rejection"):
            async with db.transaction(tenant_id=tenant, actor="x") as conn:
                await conn.execute(
                    text(
                        "INSERT INTO app.proposals (id, tenant_id, kind, payload, summary, evidence, proposed_by, "
                        "status, version, created_at, decided_by) VALUES (:i, :t, 'note', '{}', 's', '{}', 'a', "
                        "'rejected', 2, now(), 'bob')"
                    ),
                    {"i": uuid.uuid4(), "t": tenant},
                )
    finally:
        await db.dispose()


async def test_a_langgraph_approval_survives_a_restart_and_runs_once(migrated: str) -> None:
    ran: list[UUID] = []

    async def run(pid: UUID, by: str, tenant: UUID) -> None:
        ran.append(pid)

    pid = uuid.uuid7()
    async with open_checkpointer(migrated, "app_user") as saver:
        await LangGraphApprovalWorkflow(saver, run).start(pid)
    assert ran == []
    async with open_checkpointer(migrated, "app_user") as saver:  # a new process: state came back from Postgres
        wf = LangGraphApprovalWorkflow(saver, run)
        await wf.resume(pid, approved=True, decided_by="bob", tenant_id=UUID(int=3))
        await wf.resume(pid, approved=True, decided_by="bob", tenant_id=UUID(int=3))
    assert ran == [pid]


async def test_our_checkpoint_tables_match_langgraphs_own(migrated: str) -> None:
    """Built by the library's own setup() in a scratch schema, then compared column by column and index by index."""
    url = libpq_url(migrated)
    async with await AsyncConnection.connect(url, autocommit=True, row_factory=dict_row) as admin:
        await admin.execute("DROP SCHEMA IF EXISTS lg_reference CASCADE")
        await admin.execute("CREATE SCHEMA lg_reference")
    async with await AsyncConnection.connect(
        url, autocommit=True, prepare_threshold=0, row_factory=dict_row, options="-c search_path=lg_reference"
    ) as conn:
        await AsyncPostgresSaver(conn=conn).setup()

    async def shape(schema: str) -> tuple[list[tuple[object, ...]], list[str], int]:
        async with await AsyncConnection.connect(url, autocommit=True) as c:
            cols = await (
                await c.execute(
                    "SELECT table_name, column_name, data_type, is_nullable, column_default FROM "
                    "information_schema.columns WHERE table_schema = %s ORDER BY 1, 2",
                    (schema,),
                )
            ).fetchall()
            idx = await (
                await c.execute(
                    "SELECT replace(indexdef, %s, '') FROM pg_indexes WHERE schemaname = %s ORDER BY 1",
                    (schema + ".", schema),
                )
            ).fetchall()
            top = await (await c.execute(f"SELECT max(v) FROM {schema}.checkpoint_migrations")).fetchone()  # noqa: S608
        return [tuple(r) for r in cols], [r[0] for r in idx], int(top[0]) if top else -1

    ours, theirs = await shape("agent_checkpoints"), await shape("lg_reference")
    assert ours[0] == theirs[0], "the checkpoint columns differ from LangGraph's: add a migration for the new version"
    assert ours[1] == theirs[1], "the checkpoint indexes differ from LangGraph's"
    assert ours[2] == theirs[2] == LIBRARY_MIGRATIONS - 1
