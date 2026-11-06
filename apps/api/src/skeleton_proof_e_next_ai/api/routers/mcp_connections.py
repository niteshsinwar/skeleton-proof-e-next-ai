"""Outside MCP servers for this tenant (04/K3): which are allowed, which are connected, what changed upstream.

Connecting stores the tenant's OAuth client for a server, sealed; only an admin, in person, may do it. Reviewing calls
the server, so it runs with no transaction open.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ...application import outside_tools as uc
from ...domain.outside_tools import Credentials
from ...persistence.mcp_connections import PgMcpConnections
from ...persistence.records import PgAudit
from ..deps import AppState, CurrentPrincipal, now, rate_limited, state
from ..errors import ProblemError

router = APIRouter(prefix="/ai/mcp/servers", tags=["ai"])


class ToolOut(BaseModel):
    name: str
    kind: Literal["read", "propose"]


class ServerOut(BaseModel):
    server: str
    tools: list[ToolOut]
    connected: bool
    client_id: str | None
    connected_by: str | None
    connected_at: datetime | None


class Connect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(min_length=1, max_length=2000)


class DriftOut(BaseModel):
    tool: str
    reason: Literal["changed", "missing", "unreviewed"]


def _sealing(st: AppState) -> None:
    if st.mcp_box is None:
        raise ProblemError(503, "mcp-not-configured", "Outside servers can't be connected until a sealing key is set.")


@router.get("", response_model=list[ServerOut], dependencies=[rate_limited("read")])
async def list_servers(request: Request, principal: CurrentPrincipal) -> list[ServerOut]:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        ports = uc.Ports(PgMcpConnections(conn, st.mcp_box), PgAudit(conn))
        connected = {c.server: c for c in await uc.connections(ports, principal)}
    out = []
    for server in st.mcp_tools.servers():
        c = connected.get(server)
        offered = [t for t in st.mcp_tools.tools() if t.server == server]
        tools = [ToolOut.model_validate({"name": t.name, "kind": t.kind.value}) for t in offered]
        out.append(
            ServerOut(
                server=server,
                tools=tools,
                connected=c is not None,
                client_id=c.client_id if c else None,
                connected_by=c.connected_by if c else None,
                connected_at=c.connected_at if c else None,
            )
        )
    return out


@router.put("/{server}/connection", status_code=204, dependencies=[rate_limited("write")])
async def connect_server(server: str, body: Connect, request: Request, principal: CurrentPrincipal) -> Response:
    st = state(request)
    _sealing(st)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        await uc.connect(
            uc.Ports(PgMcpConnections(conn, st.mcp_box), PgAudit(conn)),
            st.mcp_tools,
            principal,
            server,
            Credentials(body.client_id, body.client_secret),
            now(),
        )
    return Response(status_code=204)


@router.delete("/{server}/connection", status_code=204, dependencies=[rate_limited("write")])
async def disconnect_server(server: str, request: Request, principal: CurrentPrincipal) -> Response:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        await uc.disconnect(uc.Ports(PgMcpConnections(conn, st.mcp_box), PgAudit(conn)), principal, server)
    return Response(status_code=204)


@router.post("/{server}/review", response_model=list[DriftOut], dependencies=[rate_limited("write")])
async def review_server(server: str, request: Request, principal: CurrentPrincipal) -> list[DriftOut]:
    """Every difference between the reviewed tools in ai/mcp-servers.yaml and what the server offers now."""
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        ports = uc.Ports(PgMcpConnections(conn, st.mcp_box), PgAudit(conn))
        credentials = await uc.credentials_for_review(ports, st.mcp_tools, principal, server)
    drift = await st.mcp_tools.review(server, credentials, principal.tenant_id)
    return [DriftOut(tool=d.tool, reason=d.reason) for d in drift]
