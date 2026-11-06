"""Outside tools (04/K3): connecting a tenant to an outside MCP server, and the handler and executor that let agents
use its tools. A read tool runs and its result returns to the model as untrusted text; a write tool only ever creates a
proposal, which runs once after a person approves it (04/K1, README #9).

Calls to an outside server are network calls. The handler is given its credential lookup and its proposal writer by
the composition root, each with its own short transaction, so no transaction stays open during a call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from ..domain.ai import ExecutionFailed, Proposal, ToolKind, ToolResult
from ..domain.errors import InvariantViolated, NotFound
from ..domain.outside_tools import Connection, Credentials, OutsideTool
from ..domain.ports import AuditEvent, AuditPort, McpConnections, OutsideTools
from ..domain.principals import Capability, Principal

PROPOSAL_KIND = "outside_tool"  # one kind for every outside write; the payload names the tool


@dataclass(frozen=True, slots=True)
class Ports:
    connections: McpConnections
    audit: AuditPort


def _known(tools: OutsideTools, server: str) -> None:
    if server not in tools.servers():
        raise NotFound("No such outside server.")


async def connect(
    ports: Ports, tools: OutsideTools, principal: Principal, server: str, credentials: Credentials, now: datetime
) -> None:
    principal.require(Capability.MCP_CONNECT)
    _known(tools, server)
    if not credentials.client_id.strip() or not credentials.client_secret:
        raise InvariantViolated("Give the client id and secret the outside server issued for this tenant.")
    await ports.connections.put(principal.tenant_id, server, credentials, principal.subject, now)
    await _audit(ports, principal, "mcp.connected", server, f"client {credentials.client_id}")


async def disconnect(ports: Ports, principal: Principal, server: str) -> None:
    principal.require(Capability.MCP_CONNECT)
    if not await ports.connections.delete(principal.tenant_id, server):
        raise NotFound("This tenant is not connected to that server.")
    await _audit(ports, principal, "mcp.disconnected", server, None)


async def connections(ports: Ports, principal: Principal) -> list[Connection]:
    principal.require(Capability.MCP_CONNECT)
    return await ports.connections.list(principal.tenant_id)


async def credentials_for_review(
    ports: Ports, tools: OutsideTools, principal: Principal, server: str
) -> Credentials | None:
    principal.require(Capability.MCP_CONNECT)
    _known(tools, server)
    return await ports.connections.credentials(principal.tenant_id, server)


class OutsideToolHandler:
    """Implements `ToolHandler` for outside tools, for an agent loop (intelligence/orchestration.py)."""

    def __init__(
        self,
        tools: OutsideTools,
        credentials: Callable[[UUID, str], Awaitable[Credentials | None]],
        propose: Callable[[OutsideTool, Mapping[str, Any], Principal], Awaitable[UUID]],
    ) -> None:
        self._tools, self._credentials, self._propose = tools, credentials, propose

    async def call(self, name: str, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        tool = self._tools.tool(name)
        if tool is None:
            return ToolResult(ok=False, text="", error="unknown_tool")
        if tool.kind is ToolKind.PROPOSE:
            proposal_id = await self._propose(tool, arguments, principal)
            return ToolResult(ok=True, text=f"Proposed {tool.key}; a person decides.", proposal_id=proposal_id)
        credentials = await self._credentials(principal.tenant_id, tool.server)
        return await self._tools.call(tool, arguments, credentials, principal.tenant_id)


def proposal_for(tool: OutsideTool, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """What `proposals.propose` is given for an outside write: the tool and its exact arguments, for the decider."""
    return {
        "kind": PROPOSAL_KIND,
        "payload": {"tool": tool.key, "arguments": dict(arguments)},
        "summary": f"Call {tool.name} on {tool.server}.",
        "evidence": {"tool_description": tool.description},
    }


class OutsideToolExecutor:
    """Implements `ProposalExecutor` for `outside_tool` proposals. The call runs as the approver's tenant connection."""

    def __init__(self, tools: OutsideTools, connections: McpConnections) -> None:
        self._tools, self._connections = tools, connections

    async def precheck(self, p: Proposal, principal: Principal) -> str | None:
        tool = self._tools.tool(str(p.payload.get("tool", "")))
        if tool is None or tool.kind is not ToolKind.PROPOSE:
            return "That outside tool is no longer offered as a write."
        return None

    async def execute(self, p: Proposal, principal: Principal) -> Mapping[str, Any]:
        tool = self._tools.tool(str(p.payload["tool"]))
        if tool is None:
            raise ExecutionFailed("tool_withdrawn")
        credentials = await self._connections.credentials(p.tenant_id, tool.server)
        result = await self._tools.call(tool, p.payload.get("arguments", {}), credentials, p.tenant_id)
        if not result.ok:
            raise ExecutionFailed(result.error or "tool_error")
        return {"result": result.text}


async def _audit(ports: Ports, principal: Principal, action: str, server: str, reason: str | None) -> None:
    await ports.audit.append(
        AuditEvent(
            action=action,
            entity="mcp_connection",
            entity_id=server,
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=None,
            after_version=None,
            reason=reason,
        )
    )
