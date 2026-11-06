"""Outside MCP server credentials per tenant (implements `McpConnections`). Secrets are sealed before they are written
and opened only when a call needs them; a value that won't open fails the call, never falls back (02/B7)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.outside_tools import Connection, Credentials
from ..security.sealed import SecretBox
from .schema import mcp_connections


def _context(tenant_id: UUID, server: str) -> str:
    return f"mcp:{tenant_id}:{server}:client_secret"


class PgMcpConnections:
    def __init__(self, conn: AsyncConnection, box: SecretBox | None) -> None:
        self.conn, self.box = conn, box

    def _box(self) -> SecretBox:
        if self.box is None:
            raise RuntimeError("APP_MCP_SECRETS_KEY is not set, so no outside server can be connected")
        return self.box

    async def put(self, tenant_id: UUID, server: str, credentials: Credentials, by: str, at: datetime) -> None:
        sealed = self._box().seal(credentials.client_secret, context=_context(tenant_id, server))
        values = {
            "client_id": credentials.client_id,
            "client_secret_sealed": sealed,
            "connected_by": by,
            "connected_at": at,
        }
        await self.conn.execute(
            insert(mcp_connections)
            .values(tenant_id=tenant_id, server=server, **values)
            .on_conflict_do_update(index_elements=["tenant_id", "server"], set_=values)
        )

    async def credentials(self, tenant_id: UUID, server: str) -> Credentials | None:
        row = (
            await self.conn.execute(
                select(mcp_connections.c.client_id, mcp_connections.c.client_secret_sealed).where(
                    mcp_connections.c.tenant_id == tenant_id, mcp_connections.c.server == server
                )
            )
        ).one_or_none()
        if row is None:
            return None
        secret = self._box().open(row.client_secret_sealed, context=_context(tenant_id, server))
        return Credentials(row.client_id, secret)

    async def list(self, tenant_id: UUID) -> list[Connection]:
        rows = await self.conn.execute(
            select(
                mcp_connections.c.server,
                mcp_connections.c.client_id,
                mcp_connections.c.connected_by,
                mcp_connections.c.connected_at,
            )
            .where(mcp_connections.c.tenant_id == tenant_id)
            .order_by(mcp_connections.c.server)
        )
        return [Connection(r.server, r.client_id, r.connected_by, r.connected_at) for r in rows]

    async def delete(self, tenant_id: UUID, server: str) -> bool:
        result = await self.conn.execute(
            delete(mcp_connections).where(mcp_connections.c.tenant_id == tenant_id, mcp_connections.c.server == server)
        )
        return bool(result.rowcount)
