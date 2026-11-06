"""EXAMPLE SLICE — the work-item state machine as a table (02/D13). Deterministic; no model decides a transition."""

from __future__ import annotations

from ..domain.work_items import Command, State

TRANSITIONS: dict[tuple[State, Command], State] = {
    (State.DRAFT, Command.SUBMIT): State.SUBMITTED,
    (State.SUBMITTED, Command.APPROVE): State.APPROVED,
    (State.SUBMITTED, Command.REJECT): State.REJECTED,
}


def next_state(current: State, command: Command) -> State | None:
    return TRANSITIONS.get((current, command))


def legal_commands(current: State) -> list[Command]:
    return [cmd for (state, cmd) in TRANSITIONS if state is current]
