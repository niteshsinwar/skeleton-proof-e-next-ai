"""The product AI's value objects (04): pure, with no I/O and no provider types.

A model's answer is untrusted input (README #8). It reaches the application only as an `Attempt`: what the model was
shown, what was asked, what it said, the verified result, and what it cost. Code reads the verified result and decides
what happens next; it never reads the raw text to decide anything (04/P6: "no prose scanning").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from .errors import DomainError, Forbidden, IllegalTransition, InvariantViolated

GLOBAL_KILL_SWITCH = "ai"  # off: every AI step is off for the tenant (05/SG11)


def kill_switch(step: str) -> str:
    """The flag that turns one step off per tenant. Flags are audited; an unset flag means on."""
    return f"ai.{step}"


class ExecutionMode(StrEnum):
    """Every record says how it was produced, so a fixture or an AI-off run is never read as evidence (06/T4)."""

    LIVE = "live"  # a real provider answered
    FIXTURE = "fixture"  # the labelled fake answered: a harness test, never an eval
    AI_OFF = "ai_off"  # no model was called: switched off, unconfigured or over budget


class AttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"  # valid, verified output
    ABSTAINED = "abstained"  # the model, or a verifier, said "I cannot" (a first-class outcome, 04/Q5)
    INVALID = "invalid"  # malformed, truncated, unverified or unsafe output: rejected, never repaired (04/Q4, P6)
    REFUSED = "refused"  # the provider declined for policy reasons
    FAILED = "failed"  # no usable answer: provider down, timeout, configuration (fails closed, 04/P5)


class Trust(StrEnum):
    """Where a context item came from. Only the agent file's own policy text is trusted; everything else is data."""

    RECORD = "record"  # our stored data, written by people through our API
    USER = "user"  # what the caller typed in this request
    EXTERNAL = (
        "external"  # files people send, web pages, tool output, other systems: hostile by default (05/SG5, 05/SG6)
    )


class DataClass(StrEnum):
    """05/SG7: decides logging, retention and what may reach a provider (04/M4)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    REGULATED = "regulated"


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One thing the model may be shown. The use case builds it from records it has already authorised (02/Z5)."""

    source: str  # what kind of thing this is, e.g. "work_item.details"; the agent file allowlists sources (04/M4)
    ref: str  # which record it came from, kept for provenance; never shown to the model as an identifier
    text: str
    trust: Trust
    tenant_id: UUID
    data_class: DataClass = DataClass.INTERNAL
    may_drive_action: bool = False  # 04/X1: only text that may cause an action says so
    stable: bool = False  # the same on every call (cacheable, ordered first, 04/X2)

    def __post_init__(self) -> None:
        if not self.source or not self.ref:
            raise InvariantViolated("A context item names its source and the record it came from.")
        if self.trust is Trust.EXTERNAL and self.may_drive_action:
            raise InvariantViolated("External text can never drive an action (05/SG5).")
        if self.data_class is DataClass.REGULATED:
            raise InvariantViolated(
                "Regulated data never reaches a model without an ADR naming the agreement (05/SG9)."
            )


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """04/X1: what the model was shown, or why an item was dropped. `id` is what the model cites (e.g. "c1")."""

    id: str
    item: ContextItem
    included: bool
    drop_reason: str | None
    token_estimate: int  # an estimate for budgeting only; never reported as usage (Aegis I §11)
    signals: tuple[str, ...] = ()  # injection-screen findings: they only ever raise risk (04/P4)

    def __post_init__(self) -> None:
        if self.included == (self.drop_reason is not None):
            raise InvariantViolated("An entry is either included or dropped with a reason, never both or neither.")


@dataclass(frozen=True, slots=True)
class Usage:
    """Provider-reported usage and the cost computed from a dated price snapshot. Unknown is None, never zero."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: Decimal | None = None
    price_snapshot: str | None = None  # which dated rate computed cost_usd

    @staticmethod
    def none_spent() -> Usage:
        """No model ran (fixture or AI off): nothing was spent, and no token count is invented."""
        return Usage(cost_usd=Decimal(0))


@dataclass(frozen=True, slots=True)
class Attempt:
    """One model call and everything needed to answer "why did the assistant say that?" (04/X6)."""

    id: UUID
    tenant_id: UUID
    step: str
    agent: str
    agent_version: int
    agent_hash: str
    route: str
    mode: ExecutionMode
    status: AttemptStatus
    started_at: datetime
    finished_at: datetime
    entity: str  # what the step was about, for the per-entity trail
    entity_id: str
    actor: str
    principal_kind: str
    on_behalf_of: str | None
    provider: str | None = None
    requested_model: str | None = None
    served_model: str | None = None  # may differ when the provider's refusal fallback answered (D4)
    reason: str | None = None  # why it isn't SUCCEEDED, as a stable code (e.g. "truncated", "provider_unavailable")
    usage: Usage = field(default_factory=Usage)
    ledger: tuple[LedgerEntry, ...] = ()  # what it was shown
    request: Mapping[str, Any] = field(default_factory=dict)  # what was asked (system prompt hash, rendered input)
    output_text: str | None = None  # what it said, verbatim
    result: Mapping[str, Any] | None = None  # the validated, verified output: the only thing code may read
    abstention: str | None = None  # why it couldn't answer, in words a person can read (only when ABSTAINED)
    signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.result is not None) != (self.status is AttemptStatus.SUCCEEDED):
            raise InvariantViolated("Only a succeeded attempt carries a result; a gated value gates every copy.")
        if self.status is not AttemptStatus.SUCCEEDED and not self.reason:
            raise InvariantViolated("An attempt that didn't succeed says why.")
        if (self.abstention is not None) != (self.status is AttemptStatus.ABSTAINED):
            raise InvariantViolated("An abstention is recorded as itself, never as another outcome (04/Q5).")
        if self.mode is not ExecutionMode.LIVE and self.usage.cost_usd not in (None, Decimal(0)):
            raise InvariantViolated("Only a live call can cost money.")
        if self.finished_at < self.started_at:
            raise InvariantViolated("An attempt can't finish before it starts.")


@dataclass(frozen=True, slots=True)
class StepInputs:
    """What a use case hands to an AI step: authorised context items and the agent file's declared variables."""

    items: tuple[ContextItem, ...]
    variables: Mapping[str, str]
    entity: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class StepResult:
    attempt: Attempt

    @property
    def succeeded(self) -> bool:
        return self.attempt.status is AttemptStatus.SUCCEEDED

    @property
    def value(self) -> Mapping[str, Any]:
        """The verified result. Reading it from anything but a succeeded attempt is a bug, so it raises."""
        if self.attempt.result is None:
            raise InvariantViolated(f"No verified result: the attempt {self.attempt.status.value}.")
        return self.attempt.result


class AIUnavailable(DomainError):
    """The model can't answer now. The product keeps working without it (01/R5); the caller may retry."""

    code = "ai-unavailable"
    status = 503

    def __init__(self, detail: str, retry_after: int = 30) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class Superseded(DomainError):
    """Late output from a superseded run (02/J6): a newer run on the same subject was recorded first, or what the
    step read changed while it ran. The attempt stays recorded; its output is never used."""

    code = "superseded"
    status = 409


class AIBudgetSpent(DomainError):
    """The tenant's AI budget for today is spent (01/R2 cost units, 07/O19): refused, never queued silently."""

    code = "ai-budget-spent"
    status = 429

    def __init__(self, detail: str, retry_after: int) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


# --- Agency: tools, proposals, budgets and handoffs (04/K1, 04/G3–G7, README #9) ---------------------------------


class ExecutionFailed(Exception):
    """An approved proposal's write failed. It is recorded as failed with the reason, never as done, and is not
    retried by itself: a person sees it and decides (04/G7)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ToolKind(StrEnum):
    READ = "read"  # runs, and its result goes back to the model as untrusted context
    PROPOSE = "propose"  # never acts: it creates a proposal that a person approves or rejects (04/K1)


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


DECIDED = {ProposalStatus.APPROVED, ProposalStatus.REJECTED, ProposalStatus.EXECUTED, ProposalStatus.FAILED}


@dataclass(frozen=True, slots=True)
class Proposal:
    """A write an agent wants, waiting for a person (README #9, 04/G7). The record of what happens is this, never a
    workflow checkpoint (01/T1). Only an approved proposal runs, once, through its kind's registered executor."""

    id: UUID
    tenant_id: UUID
    kind: str  # names the registered executor
    payload: Mapping[str, Any]
    summary: str  # what it will do, in words the approver reads beside the evidence (04/H2)
    evidence: Mapping[str, Any]  # e.g. the attempt id and the reasons, shown with it
    proposed_by: str  # who proposed it (an agent principal)
    on_behalf_of: str | None  # the person the agent works for
    status: ProposalStatus
    version: int
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    executed_at: datetime | None = None
    outcome: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise InvariantViolated("A proposal says what it will do.")
        if (self.status in DECIDED) != (self.decided_by is not None):
            raise InvariantViolated("A decided proposal records who decided it, and only a decided one does.")
        if self.status is ProposalStatus.REJECTED and not (self.decision_reason or "").strip():
            raise InvariantViolated("A rejection gives its reason (04/H2).")
        if (self.status in (ProposalStatus.EXECUTED, ProposalStatus.FAILED)) != (self.executed_at is not None):
            raise InvariantViolated("Only an executed or failed proposal has an execution time.")

    def decide(self, *, approve: bool, by: str, reason: str | None, now: datetime) -> Proposal:
        """Separation of duties (02/Z6): neither the proposer nor the person it was proposed for may decide it."""
        if self.status is not ProposalStatus.PROPOSED:
            raise IllegalTransition(f"This proposal is already {self.status.value}.", [])
        if by in (self.proposed_by, self.on_behalf_of):
            raise Forbidden("A proposal is decided by someone other than whoever it was proposed by or for.")
        status = ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED
        return replace(
            self, status=status, decided_by=by, decided_at=now, decision_reason=reason, version=self.version + 1
        )

    def finished(self, *, outcome: Mapping[str, Any], ok: bool, now: datetime) -> Proposal:
        if self.status is not ProposalStatus.APPROVED:
            raise IllegalTransition(f"Only an approved proposal runs; this one is {self.status.value}.", [])
        status = ProposalStatus.EXECUTED if ok else ProposalStatus.FAILED
        return replace(self, status=status, executed_at=now, outcome=outcome, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class Budget:
    """A run's limits (04/G5): hitting one stops the run and escalates with what was done; it never stops silently."""

    max_steps: int = 8
    max_tool_calls: int = 8
    max_cost_usd: Decimal = Decimal("0.50")
    max_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tool_calls < 0 or self.max_cost_usd < 0 or self.max_seconds <= 0:
            raise InvariantViolated("A budget has positive limits.")


@dataclass(frozen=True, slots=True)
class Handoff:
    """A typed handoff between steps, recorded (04/G3): agents never call agents; the orchestrator passes work on."""

    from_step: str
    to_step: str
    goal: str
    constraints: tuple[str, ...]
    budget: Budget


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool gave back. `text` returns to the model as external, untrusted context (05/SG5)."""

    ok: bool
    text: str
    proposal_id: UUID | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.ok == (self.error is not None):
            raise InvariantViolated("A tool result either succeeded or names its error.")
