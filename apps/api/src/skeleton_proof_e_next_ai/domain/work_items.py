"""EXAMPLE SLICE — work items. Copy its shape for real entities, then delete it.

A work item is drafted, submitted, then approved or rejected by someone other than its submitter
(02/Z6). Constructors refuse illegal states (02/B6). Which transitions exist is workflow/'s table
(02/D13); what must hold after a transition is decided here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .errors import Forbidden, InvariantViolated

MAX_TITLE = 200


class State(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class Command(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class WorkItem:
    id: UUID
    tenant_id: UUID
    title: str
    state: State
    version: int
    created_by: str
    created_at: datetime
    submitted_by: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    # Display names as they were when the person acted, like an audit record (03/F16: screens never show subjects).
    created_by_name: str | None = None
    decided_by_name: str | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise InvariantViolated("A work item needs a title.")
        if len(self.title) > MAX_TITLE:
            raise InvariantViolated(f"A title is at most {MAX_TITLE} characters.")
        if self.version < 1:
            raise InvariantViolated("Version starts at 1.")
        if self.created_at.tzinfo is None:
            raise InvariantViolated("Timestamps are timezone-aware (UTC).")
        if self.state in (State.APPROVED, State.REJECTED) and not self.decided_by:
            raise InvariantViolated("A decided item records who decided it.")
        if self.state is not State.DRAFT and not self.submitted_by:
            raise InvariantViolated("A submitted item records who submitted it.")

    def transition(
        self, command: Command, target: State, actor: str, reason: str | None = None, actor_name: str | None = None
    ) -> WorkItem:
        """Apply a transition the workflow table allowed. Never mutates: an illegal command leaves no partial state."""
        if command is Command.SUBMIT:
            return replace(self, state=target, version=self.version + 1, submitted_by=actor)
        if actor == self.submitted_by:
            raise Forbidden("The submitter cannot decide their own item (separation of duties).")
        if command is Command.REJECT and not (reason or "").strip():
            raise InvariantViolated("A rejection needs a reason.")
        return replace(
            self,
            state=target,
            version=self.version + 1,
            decided_by=actor,
            decided_by_name=actor_name,
            decision_reason=reason,
        )
