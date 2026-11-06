"""The MCP client half of the switchboard (04/K3, 05/SG5). Read against mcp 2.3.0 as installed (2026-11-05).

- Only servers listed in `ai/mcp-servers.yaml` are reachable, over HTTPS (plain HTTP only to localhost outside
  production); redirects are not followed.
- A tool is offered only as reviewed: on every call the live description and input schema must match the reviewed
  copy's fingerprint, or the call is refused as `tool_changed_upstream`. `review` lists every difference.
- Arguments are validated against the reviewed input schema before anything is sent.
- Credentials are per tenant (OAuth client_credentials). Access tokens stay in this process's memory and are fetched
  again when they expire; they are never stored. The client secret is sealed at rest by the caller.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import ParseResult, urlparse
from uuid import UUID

import httpx2
import jsonschema  # type: ignore[import-untyped]  # no stubs ship with 4.26; the calls are covered by tests
import mcp_types
import yaml
from mcp import Client
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.ai import ToolKind, ToolResult
from ..domain.outside_tools import Credentials, Drift, OutsideTool, fingerprint
from .tools import Tool

NAME = re.compile(r"^[a-z][a-z0-9_-]{0,28}$")  # `<server>__<tool>` stays within a provider's 64-character tool name
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class McpConfigError(ValueError):
    """`ai/mcp-servers.yaml` is wrong. The app refuses to start rather than guess (02/B5)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolSpec(_Strict):
    kind: Literal["read", "propose"]
    description: str = Field(min_length=1)  # the reviewed copy: what the model is shown and what the server must say
    input_schema: dict[str, Any]


class ServerSpec(_Strict):
    url: str
    auth: Literal["client_credentials", "none"] = "client_credentials"
    scope: str | None = None
    # The authorization server its credentials belong to: required with client credentials, so a server can't point
    # the flow at another issuer and receive the client secret (the SDK refuses metadata for any other issuer).
    issuer: str | None = None
    timeout_seconds: float = Field(default=20, gt=0, le=120)
    tools: dict[str, ToolSpec] = Field(default_factory=dict)


class McpConfig(_Strict):
    version: Literal[1]
    servers: dict[str, ServerSpec] = Field(default_factory=dict)


def _secure(url: ParseResult, production: bool) -> bool:
    return url.scheme == "https" or (url.scheme == "http" and url.hostname in LOCAL_HOSTS and not production)


def load(path: Path, *, production: bool) -> McpConfig:
    try:
        config = McpConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise McpConfigError(f"{path} is missing") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise McpConfigError(f"{path} is invalid: {exc}") from exc
    problems: list[str] = []
    for name, server in config.servers.items():
        if not _secure(urlparse(server.url), production):
            problems.append(f"server {name!r} must use https (plain http only to localhost outside production)")
        if server.auth == "client_credentials" and not server.issuer:
            problems.append(f"server {name!r} uses client credentials, so it names its `issuer`")
        elif server.issuer and not _secure(urlparse(server.issuer), production):
            problems.append(
                f"server {name!r}: the issuer must use https (plain http only to localhost outside production)"
            )
        problems += [f"name {n!r} must match {NAME.pattern}" for n in (name, *server.tools) if not NAME.match(n)]
        for tool, spec in server.tools.items():
            try:
                jsonschema.Draft202012Validator.check_schema(spec.input_schema)
            except jsonschema.SchemaError as exc:
                problems.append(f"{name}.{tool}: the input schema is not valid JSON Schema ({exc.message})")
    if problems:
        raise McpConfigError("; ".join(problems))
    return config


class OutsideArguments(BaseModel):
    """Outside tools take what their reviewed JSON Schema says; the gateway validates against it before sending."""

    model_config = ConfigDict(extra="allow")


class NotConnected(Exception):
    """The tenant has not connected this server."""


Connector = Callable[[ServerSpec, httpx2.Auth | None], AbstractAsyncContextManager[Client]]


@asynccontextmanager
async def http_connector(spec: ServerSpec, auth: httpx2.Auth | None) -> AsyncIterator[Client]:
    async with (
        httpx2.AsyncClient(auth=auth, timeout=spec.timeout_seconds, follow_redirects=False) as http,
        Client(streamable_http_client(spec.url, http_client=http), cache=None) as client,  # never a stale tool list
    ):
        yield client


class _MemoryTokens:
    """The SDK's TokenStorage for one tenant and server: access tokens live only in memory."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client = client_info


class McpGateway:
    """Implements the domain's `OutsideTools` port."""

    def __init__(self, config: McpConfig, *, connect: Connector = http_connector) -> None:
        self.config, self._connect = config, connect
        self._tools = {
            t.key: t
            for server, spec in config.servers.items()
            for name, tool in spec.tools.items()
            for t in (OutsideTool(server, name, ToolKind(tool.kind), tool.description, tool.input_schema),)
        }
        self._tokens: dict[tuple[UUID, str], _MemoryTokens] = {}

    def servers(self) -> list[str]:
        return sorted(self.config.servers)

    def tools(self) -> list[OutsideTool]:
        return list(self._tools.values())

    def tool(self, key: str) -> OutsideTool | None:
        return self._tools.get(key)

    def _auth(self, server: str, credentials: Credentials | None, tenant_id: UUID) -> httpx2.Auth | None:
        spec = self.config.servers[server]
        if spec.auth == "none":
            return None
        if credentials is None:
            raise NotConnected(server)
        return ClientCredentialsOAuthProvider(
            server_url=spec.url,
            storage=self._tokens.setdefault((tenant_id, server), _MemoryTokens()),
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            scope=spec.scope,
            issuer=spec.issuer,
        )

    async def review(self, server: str, credentials: Credentials | None, tenant_id: UUID) -> list[Drift]:
        """Every difference between the reviewed tools and what the server offers now."""
        spec = self.config.servers[server]
        async with self._connect(spec, self._auth(server, credentials, tenant_id)) as client:
            live = await _live(client)
        drift = [
            Drift(name, "missing" if name not in live else "changed")
            for name, tool in spec.tools.items()
            if name not in live or _fingerprint(live[name]) != fingerprint(tool.description, tool.input_schema)
        ]
        return drift + [Drift(name, "unreviewed") for name in sorted(set(live) - set(spec.tools))]

    async def call(  # noqa: PLR0911  (one return per refusal, each a stated reason)
        self, tool: OutsideTool, arguments: Mapping[str, Any], credentials: Credentials | None, tenant_id: UUID
    ) -> ToolResult:
        try:
            jsonschema.validate(dict(arguments), dict(tool.input_schema))
        except jsonschema.ValidationError:
            return ToolResult(ok=False, text="", error="invalid_arguments")
        spec = self.config.servers[tool.server]
        try:
            async with self._connect(spec, self._auth(tool.server, credentials, tenant_id)) as client:
                live = (await _live(client)).get(tool.name)
                if live is None or _fingerprint(live) != tool.fingerprint:
                    return ToolResult(ok=False, text="", error="tool_changed_upstream")
                result = await client.call_tool(tool.name, dict(arguments), read_timeout_seconds=spec.timeout_seconds)
        except NotConnected:
            return ToolResult(ok=False, text="", error="not_connected")
        except OAuthFlowError:
            return ToolResult(ok=False, text="", error="auth_failed")  # the server's authorization refused us
        except MCPError, httpx2.HTTPError, OSError, TimeoutError, ExceptionGroup:
            return ToolResult(ok=False, text="", error="server_unavailable")  # every way an outside server fails
        if result.is_error:
            return ToolResult(ok=False, text="", error="tool_error")
        text = "\n".join(b.text for b in result.content if isinstance(b, mcp_types.TextContent))
        return ToolResult(ok=True, text=text)


async def _live(client: Client) -> dict[str, mcp_types.Tool]:
    tools: dict[str, mcp_types.Tool] = {}
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools |= {t.name: t for t in page.tools}
        cursor = page.next_cursor
        if not cursor:
            return tools


def _fingerprint(tool: mcp_types.Tool) -> str:
    return fingerprint(tool.description or "", tool.input_schema)


def registry_tools(gateway: McpGateway) -> tuple[Tool, ...]:
    """Outside tools join the one tool registry under their `<server>__<tool>` keys (02/B4)."""
    return tuple(Tool(t.key, t.kind, t.description, OutsideArguments, timeout_seconds=30.0) for t in gateway.tools())
