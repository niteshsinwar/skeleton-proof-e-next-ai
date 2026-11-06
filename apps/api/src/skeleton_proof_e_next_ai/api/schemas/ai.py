"""The generic AI API's contracts: strict in, explicit allowlist out (02/A8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...domain.ai import Proposal


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StepStatus(BaseModel):
    name: str
    available: bool  # a provider is configured for its route
    switched_on: bool  # neither the global nor the step's kill switch is off for this tenant


class AIStatus(BaseModel):
    """What screens show so a degraded or switched-off AI is always visible (01/R5)."""

    switched_on: bool
    steps: list[StepStatus]


class Feedback(_In):
    verdict: Literal["helpful", "wrong", "unsafe"]
    correction: str | None = Field(default=None, max_length=4000)  # what the answer should have been


class ShownItem(BaseModel):
    context_id: str
    source: str
    ref: str
    trust: str
    data_class: str
    included: bool
    drop_reason: str | None
    token_estimate: int
    signals: list[str]
    text: str


class AttemptOut(BaseModel):
    """Why did the assistant say that: what it was shown, asked and said, its outcome and its cost (04/X6)."""

    id: UUID
    step: str
    agent: str
    agent_version: int
    agent_hash: str
    route: str
    mode: str
    status: str
    reason: str | None
    abstention: str | None
    provider: str | None
    requested_model: str | None
    served_model: str | None
    started_at: datetime
    finished_at: datetime
    entity: str
    entity_id: str
    actor: str
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    cost_usd: Decimal | None
    price_snapshot: str | None
    signals: list[str]
    shown: list[ShownItem]
    asked: list[dict[str, Any]]
    said: dict[str, Any] | None


class Decision(_In):
    reason: str | None = Field(default=None, max_length=2000)


class ProposalOut(BaseModel):
    id: UUID
    kind: str
    payload: dict[str, Any]
    summary: str
    evidence: dict[str, Any]
    proposed_by: str
    on_behalf_of: str | None
    status: str
    version: int
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    decision_reason: str | None
    executed_at: datetime | None
    outcome: dict[str, Any] | None

    @classmethod
    def of(cls, p: Proposal) -> ProposalOut:
        return cls(
            id=p.id,
            kind=p.kind,
            payload=dict(p.payload),
            summary=p.summary,
            evidence=dict(p.evidence),
            proposed_by=p.proposed_by,
            on_behalf_of=p.on_behalf_of,
            status=p.status.value,
            version=p.version,
            created_at=p.created_at,
            decided_by=p.decided_by,
            decided_at=p.decided_at,
            decision_reason=p.decision_reason,
            executed_at=p.executed_at,
            outcome=dict(p.outcome) if p.outcome is not None else None,
        )


class ProposalList(BaseModel):
    items: list[ProposalOut]
