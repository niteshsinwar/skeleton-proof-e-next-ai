"""EXAMPLE SLICE: an AI step reached from a route, in the shape every AI feature follows (application/ai_runs.py).

1. First transaction: load and authorise what the step may see (the work-item use case), then admit the call.
2. No transaction open: run the step. It never raises for a model failure; it returns a result.
3. Second transaction: record the attempt, whatever happened. Only a verified result is returned as a brief, and only
   if no newer brief was asked for and the work item didn't change while it was written (409 otherwise, 02/J6).

A failed step answers 503 with Retry-After (fail closed, 04/P5); the work item itself is untouched, so the product
keeps working without the AI (01/R5).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...application import ai_runs
from ...application import work_items as uc
from ...domain.ai import AIUnavailable, AttemptStatus, ContextItem, StepInputs, Superseded, Trust
from ...persistence.ai_records import PgAttemptLog
from ...persistence.records import PgFlags
from ..deps import CurrentPrincipal, now, rate_limited, state
from .work_items import _ports as work_item_ports

router = APIRouter(prefix="/work-items", tags=["work items (example)"])
STEP = "work_item_brief"


class BriefOut(BaseModel):
    attempt_id: UUID
    status: str
    abstention: str | None
    points: list[dict[str, Any]]


@router.post("/{item_id}/brief", response_model=BriefOut, dependencies=[rate_limited("write")])
async def brief_work_item(item_id: UUID, request: Request, principal: CurrentPrincipal) -> BriefOut:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        item = await uc.get(work_item_ports(conn, principal), principal, item_id)
        await ai_runs.admit(
            ai_runs.Ports(PgAttemptLog(conn), PgFlags(conn)),
            principal,
            STEP,
            daily_cap_usd=st.ai_daily_cap_usd,
            now=now(),
        )
    shown = ContextItem("work_item.title", f"work_item:{item.id}", item.title, Trust.RECORD, item.tenant_id)
    result = await st.ai.run(STEP, StepInputs((shown,), {}, "work_item", str(item.id)), principal)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        current = await ai_runs.record(ai_runs.Ports(PgAttemptLog(conn), PgFlags(conn)), result)
        now_item = await uc.get(work_item_ports(conn, principal), principal, item_id)
    if not current or now_item.version != item.version:
        raise Superseded("A newer brief was asked for, or the work item changed while this one was written. Ask again.")
    attempt = result.attempt
    if attempt.status is AttemptStatus.FAILED:
        raise AIUnavailable("The assistant can't answer right now; the work item is unaffected.", retry_after=30)
    points = list(result.value.get("points", [])) if result.succeeded else []
    return BriefOut(attempt_id=attempt.id, status=attempt.status.value, abstention=attempt.abstention, points=points)
