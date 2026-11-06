"""LangGraph's Postgres checkpointer, in its own schema and as the app role (02/D7, 01/T1).

The tables are created by our Alembic migration from a pinned copy of LangGraph's own DDL, so the migration stays the
one owner of the schema (02/D2). An integration test builds LangGraph's tables with its own `setup()` beside ours and
fails on any difference, so a LangGraph upgrade that changes them arrives as a new migration, never behind our back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row

SCHEMA = "agent_checkpoints"

LIBRARY_MIGRATIONS = 10  # LangGraph's migrations our DDL covers, recorded in checkpoint_migrations (setup() is a no-op)


def libpq_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@asynccontextmanager
async def open_checkpointer(database_url: str, app_role: str | None) -> AsyncIterator[AsyncPostgresSaver]:
    """A checkpointer on its own connection, as the unprivileged app role, seeing only its own schema."""
    options = f"-c search_path={SCHEMA}" + (f" -c role={app_role}" if app_role else "")
    async with await AsyncConnection.connect(
        libpq_url(database_url), autocommit=True, prepare_threshold=0, row_factory=dict_row, options=options
    ) as conn:
        yield AsyncPostgresSaver(conn=conn)
