"""Proposals store (README #9): rows rebuilt into domain objects through their constructor (02/B6); saved by version."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.ai import Proposal, ProposalStatus
from .schema import proposals


def _row(p: Proposal) -> dict[str, Any]:
    return {
        "kind": p.kind,
        "payload": dict(p.payload),
        "summary": p.summary,
        "evidence": dict(p.evidence),
        "proposed_by": p.proposed_by,
        "on_behalf_of": p.on_behalf_of,
        "status": p.status.value,
        "version": p.version,
        "created_at": p.created_at,
        "decided_by": p.decided_by,
        "decided_at": p.decided_at,
        "decision_reason": p.decision_reason,
        "executed_at": p.executed_at,
        "outcome": dict(p.outcome) if p.outcome is not None else None,
    }


def _proposal(r: Any) -> Proposal:
    return Proposal(
        id=r.id,
        tenant_id=r.tenant_id,
        kind=r.kind,
        payload=r.payload,
        summary=r.summary,
        evidence=r.evidence,
        proposed_by=r.proposed_by,
        on_behalf_of=r.on_behalf_of,
        status=ProposalStatus(r.status),
        version=r.version,
        created_at=r.created_at,
        decided_by=r.decided_by,
        decided_at=r.decided_at,
        decision_reason=r.decision_reason,
        executed_at=r.executed_at,
        outcome=r.outcome,
    )


class PgProposals:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def add(self, proposal: Proposal) -> None:
        await self.conn.execute(
            insert(proposals).values(id=proposal.id, tenant_id=proposal.tenant_id, **_row(proposal))
        )

    async def get(self, proposal_id: UUID) -> Proposal | None:
        row = (await self.conn.execute(select(proposals).where(proposals.c.id == proposal_id))).first()
        return _proposal(row) if row else None

    async def save(self, proposal: Proposal, expected_version: int) -> bool:
        result = await self.conn.execute(
            update(proposals)
            .where(proposals.c.id == proposal.id, proposals.c.version == expected_version)
            .values(**_row(proposal))
        )
        return result.rowcount == 1

    async def list_open(self, *, limit: int) -> list[Proposal]:
        rows = await self.conn.execute(
            select(proposals)
            .where(proposals.c.status == ProposalStatus.PROPOSED.value)
            .order_by(proposals.c.created_at)
            .limit(limit)
        )
        return [_proposal(r) for r in rows]
