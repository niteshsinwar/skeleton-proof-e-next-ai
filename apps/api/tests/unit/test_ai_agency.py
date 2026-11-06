"""Agency: proposals, the approval workflows, tools and orchestration (README #9, 04/K1–K2, 04/G1–G7, 02/Z6, 02/J7).

Failure replays: an agent loops until its money runs out (04 §8); a fan-out silently loses results (04 §8); an injected
instruction makes a write happen without a person (05 §5): here a propose tool can only propose, and nothing runs before
approval; a resumed workflow runs its side effect twice (13 §4).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict

from skeleton_proof_e_next_ai.application import proposals as prop
from skeleton_proof_e_next_ai.domain.ai import (
    Attempt,
    AttemptStatus,
    Budget,
    ExecutionMode,
    Proposal,
    ProposalStatus,
    StepInputs,
    StepResult,
    ToolKind,
    ToolResult,
    Trust,
    Usage,
)
from skeleton_proof_e_next_ai.domain.errors import (
    Forbidden,
    IllegalTransition,
    InvariantViolated,
    VersionMismatch,
)
from skeleton_proof_e_next_ai.domain.ports import AuditEvent
from skeleton_proof_e_next_ai.domain.principals import Principal, PrincipalKind
from skeleton_proof_e_next_ai.intelligence import orchestration as orch
from skeleton_proof_e_next_ai.intelligence.gateway import Gateway
from skeleton_proof_e_next_ai.intelligence.graphs.approval import LangGraphApprovalWorkflow
from skeleton_proof_e_next_ai.intelligence.providers.fake import FakeProvider, Reply
from skeleton_proof_e_next_ai.intelligence.registry import Registry, Step, check
from skeleton_proof_e_next_ai.intelligence.steps import StepRunner
from skeleton_proof_e_next_ai.intelligence.tools import Tool, ToolRegistry, call_tool

from .ai_support import TENANT, Clock, agents, catalogue, item

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def person(subject: str, roles: set[str] | None = None, **kw: Any) -> Principal:
    return Principal(
        subject=subject,
        kind=kw.pop("kind", PrincipalKind.HUMAN),
        tenant_id=TENANT,
        roles=frozenset(roles or {"approver"}),
        stepped_up=kw.pop("stepped_up", True),  # a passkey sign-in just now: tier E requires it to decide (02/Z3)
        **kw,
    )


AGENT = person("agent-1", {"approver"}, kind=PrincipalKind.AGENT, on_behalf_of="alice")


# --- the proposal itself -------------------------------------------------------------------------------------------


def proposal(**kw: Any) -> Proposal:
    values: dict[str, Any] = {
        "id": UUID(int=1),
        "tenant_id": TENANT,
        "kind": "note",
        "payload": {"text": "x"},
        "summary": "Add a note.",
        "evidence": {},
        "proposed_by": "agent-1",
        "on_behalf_of": "alice",
        "status": ProposalStatus.PROPOSED,
        "version": 1,
        "created_at": NOW,
    }
    return Proposal(**(values | kw))


@pytest.mark.parametrize("by", ["agent-1", "alice"])
def test_neither_the_proposer_nor_the_person_it_is_for_may_decide_it(by: str) -> None:
    with pytest.raises(Forbidden):
        proposal().decide(approve=True, by=by, reason=None, now=NOW)


def test_a_rejection_needs_a_reason_and_a_decision_is_final() -> None:
    with pytest.raises(InvariantViolated, match="reason"):
        proposal().decide(approve=False, by="bob", reason=None, now=NOW)
    approved = proposal().decide(approve=True, by="bob", reason=None, now=NOW)
    assert (approved.status, approved.version, approved.decided_by) == (ProposalStatus.APPROVED, 2, "bob")
    with pytest.raises(IllegalTransition):
        approved.decide(approve=False, by="carol", reason="changed my mind", now=NOW)


def test_only_an_approved_proposal_can_run() -> None:
    with pytest.raises(IllegalTransition):
        proposal().finished(outcome={}, ok=True, now=NOW)


# --- the use cases -------------------------------------------------------------------------------------------------


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[UUID, Proposal] = {}

    async def add(self, p: Proposal) -> None:
        self.rows[p.id] = p

    async def get(self, pid: UUID) -> Proposal | None:
        return self.rows.get(pid)

    async def save(self, p: Proposal, expected_version: int) -> bool:
        if self.rows[p.id].version != expected_version:
            return False
        self.rows[p.id] = p
        return True

    async def list_open(self, *, limit: int) -> list[Proposal]:
        return [p for p in self.rows.values() if p.status is ProposalStatus.PROPOSED][:limit]


class Audit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, e: AuditEvent) -> None:
        self.events.append(e)


class Executor:
    def __init__(self, refuse: str | None = None) -> None:
        self.ran: list[UUID] = []
        self.refuse = refuse

    async def precheck(self, p: Proposal, principal: Principal) -> str | None:
        return self.refuse

    async def execute(self, p: Proposal, principal: Principal) -> dict[str, Any]:
        self.ran.append(p.id)
        return {"done": True}


def ports(executor: Executor | None = None) -> prop.Ports:
    return prop.Ports(proposals=MemoryStore(), audit=Audit(), executors={"note": executor or Executor()})


async def proposed(p: prop.Ports) -> Proposal:
    return await prop.propose(p, AGENT, kind="note", payload={"text": "x"}, summary="Add a note.", evidence={}, now=NOW)


async def test_a_proposal_needs_a_registered_kind() -> None:
    with pytest.raises(InvariantViolated, match="No executor"):
        await prop.propose(ports(), AGENT, kind="wire_money", payload={}, summary="s", evidence={}, now=NOW)


async def test_an_agent_can_propose_but_never_decide() -> None:
    p = ports()
    made = await proposed(p)
    with pytest.raises(Forbidden):
        await prop.decide(p, AGENT, made.id, approve=True, expected_version=1, reason=None, now=NOW)
    with pytest.raises(VersionMismatch):
        await prop.decide(p, person("bob"), made.id, approve=True, expected_version=9, reason=None, now=NOW)


async def test_an_approved_proposal_runs_once_and_every_step_is_audited() -> None:
    executor = Executor()
    p = ports(executor)
    made = await proposed(p)
    await prop.decide(p, person("bob"), made.id, approve=True, expected_version=1, reason=None, now=NOW)
    first = await prop.execute(p, person("bob"), made.id, now=NOW)
    again = await prop.execute(p, person("bob"), made.id, now=NOW)
    assert (first.status, again.status, executor.ran) == (ProposalStatus.EXECUTED, ProposalStatus.EXECUTED, [made.id])
    assert [e.action for e in p.audit.events] == ["proposal.proposed", "proposal.approved", "proposal.executed"]  # type: ignore[attr-defined]


async def test_a_precheck_that_refuses_fails_the_proposal_without_running_it() -> None:
    executor = Executor(refuse="the record changed since it was proposed")
    p = ports(executor)
    made = await proposed(p)
    await prop.decide(p, person("bob"), made.id, approve=True, expected_version=1, reason=None, now=NOW)
    done = await prop.execute(p, person("bob"), made.id, now=NOW)
    assert (done.status, executor.ran, done.outcome) == (
        ProposalStatus.FAILED,
        [],
        {"refused": "the record changed since it was proposed"},
    )


async def test_an_undecided_proposal_never_runs() -> None:
    p = ports()
    made = await proposed(p)
    with pytest.raises(IllegalTransition):
        await prop.execute(p, person("bob"), made.id, now=NOW)


# --- the approval workflows: one contract, two engines --------------------------------------------------------------


def workflows(ran: list[UUID]) -> list[Any]:
    async def run(pid: UUID, by: str, tenant: UUID) -> None:
        ran.append(pid)

    return [prop.PlainApprovalWorkflow(run), LangGraphApprovalWorkflow(InMemorySaver(), run)]


@pytest.mark.parametrize("engine", [0, 1], ids=["plain", "langgraph"])
async def test_nothing_runs_before_approval_and_an_approval_runs_once(engine: int) -> None:
    ran: list[UUID] = []
    wf = workflows(ran)[engine]
    pid = UUID(int=7)
    await wf.start(pid)
    assert ran == []  # no side effect before the interrupt
    await wf.resume(pid, approved=True, decided_by="bob", tenant_id=TENANT)
    if engine == 1:
        await wf.resume(
            pid, approved=True, decided_by="bob", tenant_id=TENANT
        )  # a second resume on a finished thread does nothing
    assert ran == [pid]


@pytest.mark.parametrize("engine", [0, 1], ids=["plain", "langgraph"])
async def test_a_rejected_proposal_never_runs(engine: int) -> None:
    ran: list[UUID] = []
    wf = workflows(ran)[engine]
    await wf.start(UUID(int=8))
    await wf.resume(UUID(int=8), approved=False, decided_by="bob", tenant_id=TENANT)
    assert ran == []


async def test_a_langgraph_resume_without_a_start_does_nothing() -> None:
    ran: list[UUID] = []
    await workflows(ran)[1].resume(UUID(int=9), approved=True, decided_by="bob", tenant_id=TENANT)
    assert ran == []


# --- tools ----------------------------------------------------------------------------------------------------------


class NoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class Handler:
    def __init__(self, result: ToolResult | None = None, delay: float = 0) -> None:
        self.result = result or ToolResult(ok=True, text="found it")
        self.delay = delay
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: Any, principal: Principal) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        await asyncio.sleep(self.delay)
        return self.result


LOOKUP = Tool("lookup", ToolKind.READ, "Look up a record by its title.", NoteArgs, timeout_seconds=0.05)
PROPOSE_NOTE = Tool("propose_note", ToolKind.PROPOSE, "Propose adding a note.", NoteArgs)


@pytest.mark.parametrize(
    ("raw", "handler", "tool", "error"),
    [
        ('{"text": "a", "admin": true}', Handler(), LOOKUP, "invalid_arguments"),  # unknown field: refused
        ("not json", Handler(), LOOKUP, "invalid_arguments"),
        ('{"text": "a"}', Handler(delay=1), LOOKUP, "tool_timeout"),
        ('{"text": "a"}', Handler(ToolResult(ok=True, text="  ")), LOOKUP, "empty_result"),
        (
            '{"text": "a"}',
            Handler(ToolResult(ok=True, text="x", proposal_id=UUID(int=1))),
            LOOKUP,
            "read_tool_proposed",
        ),
    ],
)
async def test_a_tool_call_is_validated_bounded_and_checked(raw: str, handler: Handler, tool: Tool, error: str) -> None:
    result = await call_tool(tool, raw, handler, AGENT)
    assert (result.ok, result.error) == (False, error)


async def test_a_valid_call_reaches_the_handler_with_validated_arguments() -> None:
    handler = Handler()
    result = await call_tool(LOOKUP, '{"text": "Invoice 77"}', handler, AGENT)
    assert result.ok and handler.calls == [("lookup", {"text": "Invoice 77"})]


def test_the_registry_check_refuses_unknown_tools_and_ungrounded_tool_use(tmp_path: Path) -> None:
    loaded = agents(tmp_path, tools=["lookup"], output="AgentTurn")
    tools = ToolRegistry([LOOKUP])
    steps = Registry([Step("summary", "summary", 1, orch.AgentTurn)])
    assert check(steps, loaded, ToolRegistry([])) == [
        "summary@1 lists unknown tools ['lookup']",
        "summary@1 uses tools but its grounding doesn't allow 'tool_result'",
    ]
    assert check(steps, loaded, tools) == ["summary@1 uses tools but its grounding doesn't allow 'tool_result'"]


# --- orchestration, with a scripted runner ---------------------------------------------------------------------------


def attempt(status: AttemptStatus, result: dict[str, Any] | None = None, cost: str = "0") -> Attempt:
    return Attempt(
        id=UUID(int=0),
        tenant_id=TENANT,
        step="s",
        agent="a",
        agent_version=1,
        agent_hash="h",
        route="default",
        mode=ExecutionMode.LIVE,
        status=status,
        started_at=NOW,
        finished_at=NOW,
        entity="e",
        entity_id="1",
        actor="agent-1",
        principal_kind="agent",
        on_behalf_of="alice",
        usage=Usage(cost_usd=Decimal(cost)),
        result=result if status is AttemptStatus.SUCCEEDED else None,
        reason=None if status is AttemptStatus.SUCCEEDED else "provider_unavailable",
    )


class Runner:
    """Answers each step from a script, and keeps what it was asked."""

    def __init__(self, script: dict[str, list[Attempt]] | Callable[[str, StepInputs], Attempt]) -> None:
        self.script = script
        self.asked: list[tuple[str, StepInputs]] = []

    def available(self, step: str) -> bool:
        return True

    async def run(self, step: str, inputs: StepInputs, principal: Principal) -> StepResult:
        self.asked.append((step, inputs))
        if callable(self.script):
            return StepResult(self.script(step, inputs))
        return StepResult(self.script[step].pop(0))


def ok(**result: Any) -> Attempt:
    return attempt(AttemptStatus.SUCCEEDED, result)


INPUTS = StepInputs((item("Invoice 77 was approved."),), {}, "record", "1")
BUDGET = Budget(max_steps=4, max_tool_calls=2, max_cost_usd=Decimal("1"), max_seconds=60)


def turn(tool: str | None = None, args: dict[str, Any] | None = None, answer: str | None = None) -> Attempt:
    if tool:
        return ok(action="tool", tool=tool, arguments=json.dumps(args or {"text": "a"}), answer=None)
    return ok(action="finish", tool=None, arguments=None, answer=answer)


async def loop(
    script: list[Attempt], handler: Handler | None = None, budget: Budget = BUDGET, clock: Any = None
) -> orch.RunTrace:
    return await orch.agent_loop(
        Runner({"agent": script}),
        "agent",
        INPUTS,
        AGENT,
        allowed_tools=["lookup", "propose_note"],
        tools=ToolRegistry([LOOKUP, PROPOSE_NOTE]),
        handler=handler or Handler(),
        budget=budget,
        clock=clock or (lambda: NOW),
    )


async def test_a_tool_result_returns_to_the_model_as_external_text_and_the_agent_finishes() -> None:
    runner = Runner({"agent": [turn("lookup"), turn(answer="It was approved.")]})
    trace = await orch.agent_loop(
        runner,
        "agent",
        INPUTS,
        AGENT,
        allowed_tools=["lookup"],
        tools=ToolRegistry([LOOKUP]),
        handler=Handler(),
        budget=BUDGET,
        clock=lambda: NOW,
    )
    assert trace.finished and trace.final == {"answer": "It was approved."} and len(trace.attempts) == 2
    seen = runner.asked[1][1].items[-1]
    assert (seen.text, seen.trust, seen.source) == ("found it", Trust.EXTERNAL, "tool_result")


async def test_a_propose_tool_only_proposes() -> None:
    handler = Handler(ToolResult(ok=True, text="Proposal created; a person will decide.", proposal_id=UUID(int=5)))
    trace = await loop([turn("propose_note"), turn(answer="Proposed.")], handler)
    assert trace.proposals == [UUID(int=5)] and trace.finished


@pytest.mark.parametrize(
    ("script", "budget", "stopped"),
    [
        ([turn("lookup"), turn("lookup")], BUDGET, "no_progress"),  # the same call twice
        ([turn("lookup", {"text": str(n)}) for n in range(5)], BUDGET, "max_tool_calls"),
        ([turn("lookup", {"text": str(n)}) for n in range(5)], Budget(max_steps=2, max_tool_calls=9), "max_steps"),
        ([ok(action="tool", tool="delete_everything", arguments="{}", answer=None)], BUDGET, "tool_not_allowed"),
        ([attempt(AttemptStatus.FAILED)], BUDGET, "agent:failed"),
        (
            [attempt(AttemptStatus.SUCCEEDED, {"action": "tool", "tool": "lookup", "arguments": "{}"}, cost="2")],
            BUDGET,
            "max_cost_usd",
        ),
    ],
)
async def test_the_loop_stops_on_every_limit_and_escalates(script: list[Attempt], budget: Budget, stopped: str) -> None:
    trace = await loop(script, budget=budget)
    assert trace.stopped == stopped
    if stopped.startswith("max_") or stopped == "no_progress":
        assert trace.escalation is not None and trace.escalation["reason"] == stopped


async def test_the_loop_stops_on_its_wall_clock() -> None:
    ticks = iter([NOW, NOW, NOW + timedelta(seconds=61)])
    trace = await loop([turn("lookup"), turn("lookup", {"text": "b"})], clock=lambda: next(ticks))
    assert trace.stopped == "max_seconds"


async def test_a_chain_stops_where_a_link_fails_and_records_its_handoffs() -> None:
    runner = Runner({"one": [ok(n=1)], "two": [attempt(AttemptStatus.FAILED)], "three": [ok(n=3)]})
    links = [orch.Link("two", "refine it", lambda r: INPUTS), orch.Link("three", "finish it", lambda r: INPUTS)]
    trace = await orch.chain(runner, ("one", INPUTS), links, AGENT, BUDGET)
    assert trace.stopped == "two:failed" and [h.to_step for h in trace.handoffs] == ["two"]
    assert [s for s, _ in runner.asked] == ["one", "two"]


async def test_a_router_choice_outside_its_routes_is_refused() -> None:
    runner = Runner({"router": [ok(route="billing")], "billing": [ok(done=True)]})
    assert (await orch.route(runner, "router", INPUTS, AGENT, {"billing": "billing"}, BUDGET)).final == {"done": True}
    bad = await orch.route(
        Runner({"router": [ok(route="admin")]}), "router", INPUTS, AGENT, {"billing": "billing"}, BUDGET
    )
    assert bad.stopped == "unknown_route"


async def test_parallel_work_is_reconciled_and_a_lost_job_is_flagged() -> None:
    def answer(step: str, inputs: StepInputs) -> Attempt:
        if inputs.entity_id == "boom":
            raise RuntimeError("worker died")
        return ok(id=inputs.entity_id)

    jobs = [("s", StepInputs((), {}, "e", str(n))) for n in range(5)]
    whole = await orch.parallel(Runner(answer), jobs, AGENT, max_concurrency=2)
    assert whole.reconciled and len(whole.results) == 5
    broken = await orch.parallel(Runner(answer), [*jobs, ("s", StepInputs((), {}, "e", "boom"))], AGENT)
    assert not broken.reconciled and broken.lost == [5]


# --- the loop end to end through the real step runner -----------------------------------------------------------------


async def test_the_agent_loop_runs_through_the_step_runner_and_fake_provider(tmp_path: Path) -> None:
    grounding = {
        "max_context_tokens": 2000,
        "sources": {"record.details": {"max_chars": 4000}, "tool_result": {"max_chars": 4000}},
    }
    loaded = agents(tmp_path, output="AgentTurn", tools=["lookup"], grounding=grounding)
    fake = FakeProvider.scripted(
        "alpha",
        [
            Reply.json({"action": "tool", "tool": "lookup", "arguments": '{"text": "Invoice 77"}'}),
            Reply.json({"action": "finish", "answer": "Approved by finance."}),
        ],
    )
    runner = StepRunner(
        Registry([Step("summary", "summary", 1, orch.AgentTurn)]),
        loaded,
        Gateway(catalogue(), {"alpha": fake}),
        Clock(),
        lambda: "b0",
    )
    inputs = StepInputs((item("Invoice 77 was approved."),), {"audience": "reviewer"}, "record", "1")
    trace = await orch.agent_loop(
        runner,
        "summary",
        inputs,
        AGENT,
        allowed_tools=["lookup"],
        tools=ToolRegistry([LOOKUP]),
        handler=Handler(),
        budget=BUDGET,
        clock=lambda: NOW,
    )
    assert trace.finished and trace.final == {"answer": "Approved by finance."}
    assert 'trust="external"' in fake.calls[1].user and "found it" in fake.calls[1].user
