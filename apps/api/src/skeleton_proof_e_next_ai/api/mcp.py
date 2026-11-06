"""This product as an MCP server for outside agents (04/K3, 02/Z1). Read against mcp 2.3.0 as installed (2026-11-05).

- A protected resource (RFC 9728): `/.well-known/oauth-protected-resource/mcp` names our identity provider, and a call
  without a valid token is answered 401 with a `resource_metadata` pointer, so a client can find where to sign in.
- Audience-bound tokens: only tokens issued for `mcp_audience` are accepted here, never the API's, and the API refuses
  these (02/Z1). The token's scopes must include `mcp`.
- Agents are their own traffic class: every caller is an agent (a token without `act` is a client acting for its
  `sub`), so it never performs a human-only act, its capabilities are narrowed to its scopes, and it is rate limited
  as an agent (01/R3). Revocation and roles are checked on every call, as for the API (`deps.admit`).
- Capabilities are exposed one by one, below; each calls an existing use case, so its rules and audit apply.
- Stateless JSON over Streamable HTTP (01/T1); the Host header is checked against DNS rebinding.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastapi import FastAPI
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.routing import Route

from ..application import work_items as work_items_uc
from ..config.project import PROJECT_NAME
from ..config.settings import Settings
from ..domain.errors import DomainError
from ..domain.principals import Principal, PrincipalKind
from ..security.rate_limit import LIMITS
from .auth import TokenVerifier
from .deps import AppState, admit, now
from .errors import ProblemError
from .routers.work_items import _ports as work_item_ports

SCOPE = "mcp"


class _Verifier:
    """The SDK's TokenVerifier, over ours: signature, issuer, expiry and the MCP audience (02/Z1)."""

    def __init__(self, verifier: TokenVerifier) -> None:
        self._verifier = verifier

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            verified = self._verifier.verify(f"Bearer {token}")
        except ProblemError:
            return None
        p = verified.principal
        return AccessToken(
            token=token,
            client_id=p.subject,
            scopes=sorted(p.scopes or ()),
            expires_at=int(verified.expires_at.timestamp()),
            subject=p.on_behalf_of or p.subject,
        )


async def caller(st: AppState) -> Principal:
    """The agent behind this call, admitted like any API caller and rate limited as an agent."""
    access = get_access_token()
    if access is None:  # unreachable behind the SDK's bearer middleware; refused rather than assumed
        raise ToolError("Not signed in.")
    try:
        token = await admit(st, st.mcp_verifier.verify(f"Bearer {access.token}"))
    except ProblemError as exc:
        raise ToolError(exc.detail) from exc
    p = token.principal
    if p.kind is PrincipalKind.HUMAN:  # a person's MCP client acts for them, never as them
        p = replace(p, subject=f"mcp-client:{p.subject}", kind=PrincipalKind.AGENT, on_behalf_of=p.subject)
    p = replace(p, scopes=p.scopes or frozenset())  # an agent's capabilities are only those its scopes name (02/Z7)
    decision = await st.limiter.check(f"{p.tenant_id}:agent:{p.subject}:mcp", LIMITS["read"]["agent"], now())
    if not decision.allowed:
        raise ToolError(f"Too many calls; try again in {decision.retry_after_seconds} s.")
    return p


LOCAL_ONLY = "https://local-dev.invalid"  # RFC 2606: a name that can't exist, so no client is sent anywhere


def authorization_server(settings: Settings) -> str:
    """The authorization server to advertise. Locally, tokens come from scripts/dev_token.py and there is none."""
    chosen = settings.mcp_authorization_server or settings.auth_issuer
    if urlparse(chosen).scheme in ("http", "https"):
        return chosen
    if settings.env == "production":
        raise RuntimeError("set APP_MCP_AUTHORIZATION_SERVER: MCP clients must be told where to sign in")
    return LOCAL_ONLY


def build(st: AppState) -> MCPServer:
    settings = st.settings
    server: MCPServer = MCPServer(
        PROJECT_NAME,
        instructions="Tools of this product for agents acting for a signed-in person. Results are that person's data.",
        token_verifier=_Verifier(st.mcp_verifier),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(authorization_server(settings)),
            resource_server_url=AnyHttpUrl(settings.mcp_resource_url),
            required_scopes=[SCOPE],
            validate_token_resource=False,  # our verifier checks the audience itself
        ),
    )

    # EXAMPLE SLICE: one read capability, through the work-item use case (its BOLA rule applies, 02/A7).
    @server.tool(name="get_work_item", description="One work item your person may see: its title and state.")
    async def get_work_item(item_id: str) -> dict[str, Any]:
        principal = await caller(st)
        try:
            async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
                item = await work_items_uc.get(work_item_ports(conn, principal), principal, UUID(item_id))
        except (DomainError, ValueError) as exc:
            raise ToolError(str(exc) if isinstance(exc, DomainError) else "That is not a work item id.") from exc
        return {"id": str(item.id), "title": item.title, "state": item.state.value}

    return server


def mount(app: FastAPI, server: MCPServer, settings: Settings) -> None:
    """Serve the MCP endpoint and its metadata at the paths the spec fixes, beside the API's own routes."""
    asgi = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(settings.mcp_allowed_hosts), allowed_origins=[]
        ),
    )
    for route in asgi.routes:
        # The endpoint and its metadata, each served by the whole MCP app so its auth applies.
        if isinstance(route, Route):
            app.router.routes.append(Route(route.path, endpoint=asgi))
