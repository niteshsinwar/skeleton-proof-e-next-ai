"""The tool registry: one place declares every tool an agent may call (04/K1–K2, 02/B4).

Tools are narrow and typed. A **read** tool runs and its result goes back to the model as external, untrusted text
(05/SG5); a **propose** tool never acts, it creates a proposal a person decides (README #9). The application implements
the tools behind `ToolHandler`, so per-object authorisation applies (02/Z7). Every call here has its arguments
validated, a timeout, and an empty result treated as a failure, never as an answer (04/K2). An agent file lists the
tools its step may use; nothing else is offered (fewer tools is tested, not assumed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from ..domain.ai import ToolKind, ToolResult
from ..domain.ports import ToolHandler
from ..domain.principals import Principal


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    kind: ToolKind
    description: str  # what the model reads to choose it: reviewed like code, never built from data
    arguments: type[BaseModel]  # strict (extra="forbid"); validated before the handler sees anything
    timeout_seconds: float = 10.0

    @property
    def description_sha256(self) -> str:
        return hashlib.sha256(self.description.encode()).hexdigest()


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"tool {tool.name!r} is registered twice")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def for_agent(self, names: Iterable[str]) -> tuple[Tool, ...]:
        missing = [n for n in names if n not in self._tools]
        if missing:
            raise KeyError(f"unknown tools {missing}")
        return tuple(self._tools[n] for n in names)

    def __len__(self) -> int:
        return len(self._tools)


async def call_tool(tool: Tool, raw_arguments: str, handler: ToolHandler, principal: Principal) -> ToolResult:
    try:
        arguments = tool.arguments.model_validate(json.loads(raw_arguments or "{}"))
    except json.JSONDecodeError, ValidationError:
        return ToolResult(ok=False, text="", error="invalid_arguments")
    try:
        async with asyncio.timeout(tool.timeout_seconds):
            result = await handler.call(tool.name, arguments.model_dump(mode="json"), principal)
    except TimeoutError:
        return ToolResult(ok=False, text="", error="tool_timeout")
    if result.ok and not result.text.strip() and result.proposal_id is None:
        return ToolResult(ok=False, text="", error="empty_result")  # empty is a failure, never an answer (04/K2)
    if tool.kind is ToolKind.READ and result.proposal_id is not None:
        return ToolResult(ok=False, text="", error="read_tool_proposed")  # a read tool never creates a write
    return result


# The project's tools. `/ai-step` adds one here with its handler and the agent files that may use it.
TOOLS: tuple[Tool, ...] = ()
REGISTRY = ToolRegistry(TOOLS)
