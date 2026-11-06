"""The approval workflow on LangGraph: propose -> wait for a person -> run once (04/G6–G7, 13/SK5).

Same interface as `application.proposals.PlainApprovalWorkflow`, so either can run. LangGraph re-runs a node from its
top on resume, so the waiting node does nothing but wait (no side effect before an interrupt), and the side effect sits
in its own node after it. The proposal row is the record; the checkpoint is never read as one (01/T1). Resuming a
finished thread does nothing, and `run_approved` is itself idempotent, so an approval never runs twice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class _State(TypedDict):
    proposal_id: str
    approved: bool | None
    decided_by: str | None
    tenant_id: str | None


class LangGraphApprovalWorkflow:
    def __init__(
        self, checkpointer: BaseCheckpointSaver[Any], run_approved: Callable[[UUID, str, UUID], Awaitable[None]]
    ) -> None:
        self._run = run_approved
        graph = StateGraph(_State)
        graph.add_node("wait_for_decision", self._wait)
        graph.add_node("run_approved", self._run_approved)
        graph.add_edge(START, "wait_for_decision")
        graph.add_conditional_edges(
            "wait_for_decision", lambda s: "run_approved" if s["approved"] else END, ["run_approved", END]
        )
        graph.add_edge("run_approved", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _wait(state: _State) -> dict[str, Any]:
        decision = interrupt({"proposal_id": state["proposal_id"]})  # pauses here; nothing before it has effects
        return {"approved": bool(decision["approved"]), "decided_by": decision["by"], "tenant_id": decision["tenant"]}

    async def _run_approved(self, state: _State) -> dict[str, Any]:
        await self._run(UUID(state["proposal_id"]), str(state["decided_by"]), UUID(str(state["tenant_id"])))
        return {}

    @staticmethod
    def _config(proposal_id: UUID) -> Any:
        return {"configurable": {"thread_id": str(proposal_id)}}

    async def start(self, proposal_id: UUID) -> None:
        initial: _State = {"proposal_id": str(proposal_id), "approved": None, "decided_by": None, "tenant_id": None}
        await self.graph.ainvoke(initial, self._config(proposal_id))

    async def resume(self, proposal_id: UUID, *, approved: bool, decided_by: str, tenant_id: UUID) -> None:
        state = await self.graph.aget_state(self._config(proposal_id))
        if not state.next:  # never started, or already finished: nothing waits, nothing runs again
            return
        decision = {"approved": approved, "by": decided_by, "tenant": str(tenant_id)}
        await self.graph.ainvoke(Command(resume=decision), self._config(proposal_id))
