"""Proposals: the governed write path for every agent (README #9, 04/K1, 04/G6–G7, 02/Z6).

An agent's propose tool calls `propose`; nothing happens yet. A person with `proposals.decide`, who is neither the
proposer nor the person it was proposed for, approves or rejects it (`decide`). An approved proposal runs once
(`execute`) through the executor registered for its kind, after the executor's precheck re-validates live state. Every
step is audited. Use cases never commit; the route owns the transaction (02/A3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from ..domain.ai import ExecutionFailed, Proposal, ProposalStatus
from ..domain.errors import InvariantViolated, NotFound, VersionMismatch
from ..domain.ids import new_id
from ..domain.ports import AuditEvent, AuditPort, ProposalExecutor, ProposalStore
from ..domain.principals import Capability, Principal

ENTITY = "proposal"


@dataclass(frozen=True, slots=True)
class Ports:
    proposals: ProposalStore
    audit: AuditPort
    executors: Mapping[str, ProposalExecutor]  # kind -> executor; the project registers its own


async def _audit(
    ports: Ports, principal: Principal, action: str, p: Proposal, before: int | None, reason: str | None = None
) -> None:
    await ports.audit.append(
        AuditEvent(
            action=f"proposal.{action}",
            entity=ENTITY,
            entity_id=str(p.id),
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=before,
            after_version=p.version,
            reason=reason,
        )
    )


def _visible(p: Proposal | None, principal: Principal) -> Proposal:
    if p is None or p.tenant_id != principal.tenant_id:
        raise NotFound("No such proposal.")
    if not principal.can(Capability.PROPOSALS_READ) and principal.audit_actor not in (p.on_behalf_of, p.proposed_by):
        raise NotFound("No such proposal.")  # 404 for unauthorised and absent alike (02/A7)
    return p


async def propose(
    ports: Ports,
    principal: Principal,
    *,
    kind: str,
    payload: Mapping[str, Any],
    summary: str,
    evidence: Mapping[str, Any],
    now: datetime,
) -> Proposal:
    if kind not in ports.executors:
        raise InvariantViolated(f"No executor is registered for proposals of kind {kind!r}.")
    p = Proposal(
        id=new_id(),
        tenant_id=principal.tenant_id,
        kind=kind,
        payload=dict(payload),
        summary=summary,
        evidence=dict(evidence),
        proposed_by=principal.subject,
        on_behalf_of=principal.on_behalf_of,
        status=ProposalStatus.PROPOSED,
        version=1,
        created_at=now,
    )
    await ports.proposals.add(p)
    await _audit(ports, principal, "proposed", p, None, summary)
    return p


async def get(ports: Ports, principal: Principal, proposal_id: UUID) -> Proposal:
    return _visible(await ports.proposals.get(proposal_id), principal)


async def list_open(ports: Ports, principal: Principal, *, limit: int) -> list[Proposal]:
    principal.require(Capability.PROPOSALS_READ)
    return await ports.proposals.list_open(limit=limit)


async def decide(
    ports: Ports,
    principal: Principal,
    proposal_id: UUID,
    *,
    approve: bool,
    expected_version: int,
    reason: str | None,
    now: datetime,
) -> Proposal:
    """A human act: agents and services can't hold `proposals.decide` (02/Z14). No bulk form exists (03/F20)."""
    principal.require(Capability.PROPOSALS_DECIDE)
    p = _visible(await ports.proposals.get(proposal_id), principal)
    if p.version != expected_version:
        raise VersionMismatch("The proposal changed since you read it; reload it.")
    decided = p.decide(approve=approve, by=principal.subject, reason=reason, now=now)
    if not await ports.proposals.save(decided, expected_version):
        raise VersionMismatch("The proposal changed since you read it; reload it.")
    await _audit(ports, principal, decided.status.value, decided, p.version, reason)
    return decided


async def execute(ports: Ports, principal: Principal, proposal_id: UUID, *, now: datetime) -> Proposal:
    """Run an approved proposal once. Already executed or failed: return it unchanged, never run it again."""
    p = _visible(await ports.proposals.get(proposal_id), principal)
    if p.status in (ProposalStatus.EXECUTED, ProposalStatus.FAILED):
        return p
    executor = ports.executors[p.kind]
    refusal = await executor.precheck(p, principal) if p.status is ProposalStatus.APPROVED else None
    if refusal is not None:
        done = p.finished(outcome={"refused": refusal}, ok=False, now=now)
    else:
        try:
            done = p.finished(outcome=dict(await executor.execute(p, principal)), ok=True, now=now)
        except ExecutionFailed as exc:
            refusal = exc.reason
            done = p.finished(outcome={"failed": exc.reason}, ok=False, now=now)
    if not await ports.proposals.save(done, p.version):
        raise VersionMismatch("The proposal changed while it ran; it was not recorded twice.")
    await _audit(ports, principal, done.status.value, done, p.version, refusal)
    return done


class PlainApprovalWorkflow:
    """The approval workflow without a graph engine (04/G1: simplest first). `run_approved` executes in its own
    transaction; it is called only after a person approved, never before."""

    def __init__(self, run_approved: Callable[[UUID, str, UUID], Awaitable[None]]) -> None:
        self._run = run_approved

    async def start(self, proposal_id: UUID) -> None:
        return None  # nothing to do until a person decides: the proposal row is the durable state

    async def resume(self, proposal_id: UUID, *, approved: bool, decided_by: str, tenant_id: UUID) -> None:
        if approved:
            await self._run(proposal_id, decided_by, tenant_id)
