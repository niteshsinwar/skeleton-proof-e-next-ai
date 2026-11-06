"""Orchestration: the pattern ladder as plain code (04/G1–G5, 02/J7, 13/SK5). Take the lowest rung that works.

- `chain`: steps in order; a link that doesn't succeed stops the chain and says where.
- `route`: a router step picks one of a fixed set of steps; an unknown choice is refused, never defaulted (02/B5).
- `parallel`: independent steps at bounded concurrency; every dispatched job must come back, or the run is flagged.
- `agent_loop`: a bounded tool loop. Each turn is one structured output (`AgentTurn`: call a tool, or finish), so it
  works with any provider. It stops on every budget and when the agent repeats itself, and escalates with what it did.

The orchestrator sequences everything; agents never call agents (04/G3). Handoffs are typed and recorded. Nothing here
writes state: the trace's attempts are recorded by the application, and writes happen only through proposals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ..domain.ai import Attempt, Budget, ContextItem, Handoff, StepInputs, StepResult, Trust
from ..domain.ports import AIRunner, ToolHandler
from ..domain.principals import Principal
from .registry import TOOL_RESULT_SOURCE
from .tools import ToolRegistry, call_tool
from .validation import StepOutput


class AgentTurn(StepOutput):
    """One turn of a tool-using agent: call one tool, or finish with an answer."""

    action: Literal["tool", "finish"] | None = None
    tool: str | None = Field(default=None, description="The tool to call, when action is tool.")
    arguments: str | None = Field(
        default=None, description="The tool's arguments as a JSON object, when action is tool."
    )
    answer: str | None = Field(default=None, description="The final answer, when action is finish.")


@dataclass
class RunTrace:
    attempts: list[Attempt] = field(default_factory=list)  # the application records every one (04/X6)
    handoffs: list[Handoff] = field(default_factory=list)
    tool_calls: list[tuple[str, bool, str | None]] = field(default_factory=list)  # (tool, ok, error)
    proposals: list[UUID] = field(default_factory=list)
    final: Mapping[str, Any] | None = None
    stopped: str = "finished"  # "finished", or why it stopped: a budget, "no_progress", a failed step, ...
    escalation: Mapping[str, Any] | None = None

    @property
    def finished(self) -> bool:
        return self.stopped == "finished"

    def record(self, result: StepResult) -> StepResult:
        self.attempts.append(result.attempt)
        return result


@dataclass(frozen=True, slots=True)
class Link:
    step: str
    goal: str
    inputs: Callable[[Mapping[str, Any]], StepInputs]  # builds this link's inputs from the previous verified result
    constraints: tuple[str, ...] = ()


async def chain(
    runner: AIRunner, first: tuple[str, StepInputs], links: Sequence[Link], principal: Principal, budget: Budget
) -> RunTrace:
    trace = RunTrace()
    step, inputs = first
    result = trace.record(await runner.run(step, inputs, principal))
    for link in links:
        if not result.succeeded:
            trace.stopped = f"{step}:{result.attempt.status.value}"
            return trace
        trace.handoffs.append(Handoff(step, link.step, link.goal, link.constraints, budget))
        step = link.step
        result = trace.record(await runner.run(step, link.inputs(result.value), principal))
    if result.succeeded:
        trace.final = result.value
    else:
        trace.stopped = f"{step}:{result.attempt.status.value}"
    return trace


async def route(
    runner: AIRunner,
    router: str,
    inputs: StepInputs,
    principal: Principal,
    routes: Mapping[str, str],
    budget: Budget,
) -> RunTrace:
    """The router step's verified result has a `route` field naming one key of `routes`."""
    trace = RunTrace()
    picked = trace.record(await runner.run(router, inputs, principal))
    if not picked.succeeded:
        trace.stopped = f"{router}:{picked.attempt.status.value}"
        return trace
    choice = picked.value.get("route")
    if not isinstance(choice, str) or choice not in routes:
        trace.stopped = "unknown_route"  # refused, never defaulted (02/B5)
        return trace
    trace.handoffs.append(Handoff(router, routes[choice], f"handle a {choice} request", (), budget))
    result = trace.record(await runner.run(routes[choice], inputs, principal))
    if result.succeeded:
        trace.final = result.value
    else:
        trace.stopped = f"{routes[choice]}:{result.attempt.status.value}"
    return trace


@dataclass
class ParallelTrace:
    dispatched: int
    results: dict[int, StepResult] = field(default_factory=dict)
    lost: list[int] = field(default_factory=list)

    @property
    def reconciled(self) -> bool:
        """Dispatched equals returned (02/J7, 04/G4): a lost result is a flagged run, never a quiet gap."""
        return len(self.results) == self.dispatched and not self.lost


async def parallel(
    runner: AIRunner, jobs: Sequence[tuple[str, StepInputs]], principal: Principal, *, max_concurrency: int = 4
) -> ParallelTrace:
    trace = ParallelTrace(dispatched=len(jobs))
    gate = asyncio.Semaphore(max_concurrency)  # never fan out beyond what the provider allows (04/G4)

    async def one(i: int, step: str, inputs: StepInputs) -> None:
        async with gate:
            try:
                trace.results[i] = await runner.run(step, inputs, principal)
            except Exception:  # noqa: BLE001  (a job that raised is lost and flagged, never dropped quietly)
                trace.lost.append(i)

    await asyncio.gather(*(one(i, s, inp) for i, (s, inp) in enumerate(jobs)))
    return trace


async def agent_loop(  # noqa: PLR0911  (one return per stop reason, each recorded)
    runner: AIRunner,
    step: str,
    inputs: StepInputs,
    principal: Principal,
    *,
    allowed_tools: Sequence[str],
    tools: ToolRegistry,
    handler: ToolHandler,
    budget: Budget,
    clock: Callable[[], datetime],
) -> RunTrace:
    trace = RunTrace()
    started = clock()
    observations: list[ContextItem] = []
    seen: set[tuple[str, str]] = set()
    spent = Decimal(0)
    for turn in range(1, budget.max_steps + 1):
        if (clock() - started).total_seconds() > budget.max_seconds:
            return _escalate(trace, "max_seconds", turn - 1, observations)
        result = trace.record(await runner.run(step, _with(inputs, observations), principal))
        spent += result.attempt.usage.cost_usd or Decimal(0)
        if not result.succeeded:
            trace.stopped = f"{step}:{result.attempt.status.value}"
            return trace
        if spent > budget.max_cost_usd:
            return _escalate(trace, "max_cost_usd", turn, observations)
        action = AgentTurn.model_validate({k: v for k, v in result.value.items() if k in AgentTurn.model_fields})
        if action.action == "finish":
            trace.final = {"answer": action.answer}
            return trace
        name, arguments = action.tool or "", action.arguments or "{}"
        tool = tools.get(name) if name in allowed_tools else None
        if tool is None:
            trace.stopped = "tool_not_allowed"  # the agent asked for a tool its agent file doesn't list
            return trace
        if (name, arguments) in seen:
            return _escalate(trace, "no_progress", turn, observations)  # the same call twice: looping (04/G5)
        if len(trace.tool_calls) >= budget.max_tool_calls:
            return _escalate(trace, "max_tool_calls", turn, observations)
        seen.add((name, arguments))
        outcome = await call_tool(tool, arguments, handler, principal)
        trace.tool_calls.append((name, outcome.ok, outcome.error))
        if outcome.proposal_id is not None:
            trace.proposals.append(outcome.proposal_id)
        observations.append(
            ContextItem(
                source=TOOL_RESULT_SOURCE,
                ref=f"{name}#{len(trace.tool_calls)}",
                text=outcome.text if outcome.ok else f"The tool {name} failed: {outcome.error}.",
                trust=Trust.EXTERNAL,
                tenant_id=principal.tenant_id,
            )
        )
    return _escalate(trace, "max_steps", budget.max_steps, observations)


def _with(inputs: StepInputs, observations: list[ContextItem]) -> StepInputs:
    return StepInputs((*inputs.items, *observations), inputs.variables, inputs.entity, inputs.entity_id)


def _escalate(trace: RunTrace, reason: str, turns: int, observations: list[ContextItem]) -> RunTrace:
    """A budget hit escalates with a context package for the person who picks it up; it never stops silently."""
    trace.stopped = reason
    trace.escalation = {
        "reason": reason,
        "turns": turns,
        "tool_calls": [{"tool": t, "ok": ok, "error": e} for t, ok, e in trace.tool_calls],
        "proposals": [str(p) for p in trace.proposals],
        "last_observation": observations[-1].text if observations else None,
    }
    return trace
