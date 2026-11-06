"""Engine and transactions (02/A3, 02/Z10).

Every transaction runs as the unprivileged app role (SET LOCAL ROLE) with the tenant and actor set by
SET LOCAL, so grants and row-level security always apply. The route owns the transaction and commits it;
use cases and repositories never commit.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

_ROLE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class Database:
    def __init__(self, url: str, app_role: str | None, worker_role: str | None = None, pool_size: int = 5) -> None:
        for role in (app_role, worker_role):
            if role is not None and not _ROLE.match(role):
                raise ValueError("database roles must be plain lowercase identifiers")
        self.app_role, self.worker_role = app_role, worker_role
        self.engine: AsyncEngine = create_async_engine(url, pool_size=pool_size, pool_pre_ping=True)

    @asynccontextmanager
    async def transaction(
        self, *, tenant_id: UUID | None, actor: str | None, worker: bool = False
    ) -> AsyncIterator[AsyncConnection]:
        """One command, one transaction. Commits on normal exit, rolls back on any exception.

        worker=True runs as the worker role (outbox relay, job queue), which reads across tenants.
        """
        role = self.worker_role if worker else self.app_role
        async with self.engine.begin() as conn:
            if role:
                # (reviewed: the role matched _ROLE in __init__ and comes from settings, never request input)
                # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                await conn.execute(text(f'SET LOCAL ROLE "{role}"'))
            await conn.execute(select(func.set_config("app.tenant_id", str(tenant_id) if tenant_id else "", True)))
            await conn.execute(select(func.set_config("app.actor", actor or "", True)))
            yield conn

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("select 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
