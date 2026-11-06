"""Proposals (README #9, 04/G7, 02/Z6): read them, approve or reject one at a time. No bulk form exists (03/F20).

Approve and reject are named commands with If-Match and an Idempotency-Key (02/A1, A4, A5), committed before anything
runs. An approval then resumes the approval workflow, which runs the proposal once, in its own transaction, with the
approver's authority (roles read fresh from grants, 02/Z4).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from ...application import proposals as uc
from ...domain.ports import StoredResponse
from ...domain.principals import Principal, PrincipalKind
from ...persistence.proposals import PgProposals
from ...persistence.records import PgAudit, PgGrants, PgIdempotency
from ..deps import AppState, CurrentPrincipal, ExpectedVersion, IdempotencyKey, now, rate_limited, request_hash, state
from ..schemas.ai import Decision, ProposalList, ProposalOut

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _ports(conn: AsyncConnection, st: AppState) -> uc.Ports:
    return uc.Ports(
        proposals=PgProposals(conn), audit=PgAudit(conn), executors={k: f(conn) for k, f in st.ai_executors.items()}
    )


def _respond(stored: StoredResponse) -> JSONResponse:
    return JSONResponse(dict(stored.body), status_code=stored.status, headers={"ETag": f'"{stored.body["version"]}"'})


async def run_approved(st: AppState, proposal_id: UUID, decided_by: str, tenant_id: UUID) -> None:
    """What the approval workflow calls after a person approved: the proposal runs once, as that person."""
    async with st.db.transaction(tenant_id=tenant_id, actor=decided_by) as conn:
        roles = await PgGrants(conn).roles(tenant_id, decided_by)
        approver = Principal(subject=decided_by, kind=PrincipalKind.HUMAN, tenant_id=tenant_id, roles=roles)
        await uc.execute(_ports(conn, st), approver, proposal_id, now=now())


@router.get("", response_model=ProposalList, dependencies=[rate_limited("read")])
async def list_proposals(
    request: Request, principal: CurrentPrincipal, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> ProposalList:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        items = await uc.list_open(_ports(conn, st), principal, limit=limit)
    return ProposalList(items=[ProposalOut.of(p) for p in items])


@router.get("/{proposal_id}", response_model=ProposalOut, dependencies=[rate_limited("read")])
async def get_proposal(proposal_id: UUID, request: Request, principal: CurrentPrincipal) -> JSONResponse:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        p = await uc.get(_ports(conn, st), principal, proposal_id)
    return _respond(StoredResponse(200, ProposalOut.of(p).model_dump(mode="json")))


async def _decide(
    request: Request,
    principal: Principal,
    proposal_id: UUID,
    approve: bool,
    expected: int,
    key: str,
    body: dict[str, Any],
) -> JSONResponse:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        scope = f"{principal.subject}:{'approve' if approve else 'reject'}:{proposal_id}"
        digest = request_hash({**body, "if_match": expected})
        if (stored := await idem.lookup(scope, key, digest)) is not None:
            return _respond(stored)
        p = await uc.decide(
            _ports(conn, st),
            principal,
            proposal_id,
            approve=approve,
            expected_version=expected,
            reason=body.get("reason"),
            now=now(),
        )
        stored = StoredResponse(200, ProposalOut.of(p).model_dump(mode="json"))
        await idem.remember(scope, key, digest, stored)
    # Committed: now the workflow may run it (never before the decision is durable).
    await st.ai_workflow.resume(
        proposal_id, approved=approve, decided_by=principal.subject, tenant_id=principal.tenant_id
    )
    if approve:
        async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
            stored = StoredResponse(
                200, ProposalOut.of(await uc.get(_ports(conn, st), principal, proposal_id)).model_dump(mode="json")
            )
    return _respond(stored)


@router.post("/{proposal_id}/approve", response_model=ProposalOut, dependencies=[rate_limited("write")])
async def approve_proposal(
    proposal_id: UUID,
    body: Decision,
    request: Request,
    principal: CurrentPrincipal,
    expected: ExpectedVersion,
    key: IdempotencyKey,
) -> JSONResponse:
    return await _decide(request, principal, proposal_id, True, expected, key, body.model_dump())


@router.post("/{proposal_id}/reject", response_model=ProposalOut, dependencies=[rate_limited("write")])
async def reject_proposal(
    proposal_id: UUID,
    body: Decision,
    request: Request,
    principal: CurrentPrincipal,
    expected: ExpectedVersion,
    key: IdempotencyKey,
) -> JSONResponse:
    return await _decide(request, principal, proposal_id, False, expected, key, body.model_dump())
