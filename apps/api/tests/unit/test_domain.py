"""Domain and workflow: constructors refuse illegal states; only the transition table moves an item (02/B6, D13)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from skeleton_proof_e_next_ai.domain.errors import Forbidden, InvariantViolated, StepUpRequired
from skeleton_proof_e_next_ai.domain.principals import Capability, Principal, PrincipalKind
from skeleton_proof_e_next_ai.domain.work_items import Command, State, WorkItem
from skeleton_proof_e_next_ai.workflow.work_items import TRANSITIONS, legal_commands, next_state

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def draft(**kw: object) -> WorkItem:
    base: dict[str, object] = {
        "id": uuid.uuid7(),
        "tenant_id": uuid.UUID(int=1),
        "title": "Fix the gate",
        "state": State.DRAFT,
        "version": 1,
        "created_by": "alice",
        "created_at": NOW,
    }
    return WorkItem(**{**base, **kw})  # type: ignore[arg-type]


def test_constructor_refuses_illegal_states() -> None:
    for bad in (
        {"title": "  "},
        {"title": "x" * 201},
        {"version": 0},
        {"created_at": datetime(2026, 1, 1)},
        {"state": State.APPROVED, "submitted_by": "alice"},
        {"state": State.SUBMITTED},
    ):
        with pytest.raises(InvariantViolated):
            draft(**bad)


def test_happy_path_submit_then_approve() -> None:
    item = draft()
    submitted = item.transition(Command.SUBMIT, State.SUBMITTED, "alice")
    approved = submitted.transition(Command.APPROVE, State.APPROVED, "bob")
    assert (submitted.state, submitted.version, submitted.submitted_by) == (State.SUBMITTED, 2, "alice")
    assert (approved.state, approved.version, approved.decided_by) == (State.APPROVED, 3, "bob")
    assert item.state is State.DRAFT  # never mutated


def test_submitter_cannot_decide_their_own_item() -> None:
    submitted = draft().transition(Command.SUBMIT, State.SUBMITTED, "alice")
    with pytest.raises(Forbidden):
        submitted.transition(Command.APPROVE, State.APPROVED, "alice")


def test_rejection_needs_a_reason() -> None:
    submitted = draft().transition(Command.SUBMIT, State.SUBMITTED, "alice")
    with pytest.raises(InvariantViolated):
        submitted.transition(Command.REJECT, State.REJECTED, "bob", reason=" ")
    assert (
        submitted.transition(Command.REJECT, State.REJECTED, "bob", reason="duplicate").decision_reason == "duplicate"
    )


def test_terminal_states_have_no_way_out() -> None:
    assert legal_commands(State.APPROVED) == [] and legal_commands(State.REJECTED) == []
    assert next_state(State.DRAFT, Command.APPROVE) is None


@given(st.lists(st.sampled_from(list(Command)), max_size=8))
def test_any_command_sequence_only_follows_the_table(commands: list[Command]) -> None:
    """Property (06/T5): whatever is attempted, only table transitions happen and each adds exactly one version."""
    item, actors = draft(), {"submit": "alice", "approve": "bob", "reject": "bob"}
    for cmd in commands:
        target = next_state(item.state, cmd)
        if target is None:
            continue
        after = item.transition(cmd, target, actors[cmd.value], reason="because")
        assert (item.state, cmd) in TRANSITIONS and after.version == item.version + 1
        item = after


def test_agents_never_get_human_only_capabilities() -> None:
    tenant = uuid.UUID(int=1)
    human = Principal("bob", PrincipalKind.HUMAN, tenant, frozenset({"approver"}))
    agent = Principal(
        "bot",
        PrincipalKind.AGENT,
        tenant,
        frozenset({"approver"}),
        scopes=frozenset({"work_item.decide", "work_item.create"}),
        on_behalf_of="bob",
    )
    assert human.can(Capability.WORK_ITEM_DECIDE)
    assert not agent.can(Capability.WORK_ITEM_DECIDE)  # 02/Z14: no AI actor on a human act
    assert agent.can(Capability.WORK_ITEM_CREATE)


def test_agent_capabilities_are_the_users_intersected_with_scopes() -> None:
    agent = Principal(
        "bot",
        PrincipalKind.AGENT,
        uuid.UUID(int=1),
        frozenset({"member"}),
        scopes=frozenset({"work_item.create", "roles.manage"}),
        on_behalf_of="alice",
    )
    assert agent.capabilities == frozenset({Capability.WORK_ITEM_CREATE})  # roles.manage isn't the user's to give


def test_step_up_is_required_for_privileged_acts_only_at_tier_e() -> None:
    """02/Z3: phishing-resistant MFA is required for privileged roles at tier E and offered below it."""
    approver = Principal("kim", PrincipalKind.HUMAN, uuid.UUID(int=1), frozenset({"approver"}))
    with pytest.raises(StepUpRequired):
        approver.require(Capability.WORK_ITEM_DECIDE)
    replace(approver, stepped_up=True).require(Capability.WORK_ITEM_DECIDE)
    approver.require(Capability.WORK_ITEM_CREATE)  # ordinary acts never need it
