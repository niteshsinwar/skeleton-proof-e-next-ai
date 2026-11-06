"""The generic AI API (04/X6, 06/E10, 01/R5): AI status, "why did the assistant say that", and feedback.

Features keep their own named commands for their AI steps (never one `/chat` endpoint); these routes are what every
AI feature shares. An attempt is visible to the person it ran for and to holders of `ai.inspect`; to anyone else it
doesn't exist (02/A7).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from ...domain.ai import GLOBAL_KILL_SWITCH, kill_switch
from ...domain.errors import NotFound
from ...domain.ports import AuditEvent
from ...domain.principals import Capability
from ...persistence.ai_records import PgAttemptLog
from ...persistence.records import PgAudit, PgFlags
from ..deps import CurrentPrincipal, rate_limited, state
from ..schemas.ai import AIStatus, AttemptOut, Feedback, StepStatus

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AIStatus, dependencies=[rate_limited("read")])
async def ai_status(request: Request, principal: CurrentPrincipal) -> AIStatus:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        flags = PgFlags(conn)
        on = await flags.enabled(GLOBAL_KILL_SWITCH, principal.tenant_id)
        steps = [
            StepStatus(
                name=name,
                available=st.ai.available(name),
                switched_on=on and await flags.enabled(kill_switch(name), principal.tenant_id),
            )
            for name in st.ai.steps()
        ]
    return AIStatus(switched_on=on, steps=steps)


@router.get("/attempts/{attempt_id}", response_model=AttemptOut, dependencies=[rate_limited("read")])
async def get_attempt(attempt_id: UUID, request: Request, principal: CurrentPrincipal) -> AttemptOut:
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        view = await PgAttemptLog(conn).view(attempt_id)
    if view is None or (view["actor"] != principal.subject and not principal.can(Capability.AI_INSPECT)):
        raise NotFound("No such attempt.")
    return AttemptOut.model_validate(view)


@router.post("/attempts/{attempt_id}/feedback", status_code=204, dependencies=[rate_limited("write")])
async def give_feedback(attempt_id: UUID, body: Feedback, request: Request, principal: CurrentPrincipal) -> None:
    """Every correction is an eval candidate (06/E10). Saved with the person's verdict; the attempt is never edited."""
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        log = PgAttemptLog(conn)
        view = await log.view(attempt_id)
        if view is None or (view["actor"] != principal.subject and not principal.can(Capability.AI_INSPECT)):
            raise NotFound("No such attempt.")
        await log.feedback(attempt_id, principal.tenant_id, principal.audit_actor, body.verdict, body.correction)
        await PgAudit(conn).append(
            AuditEvent(
                action="ai.feedback",
                entity="ai_attempt",
                entity_id=str(attempt_id),
                actor=principal.subject,
                principal_kind=principal.kind.value,
                on_behalf_of=principal.on_behalf_of,
                tenant_id=principal.tenant_id,
                before_version=None,
                after_version=None,
                reason=body.verdict,
            )
        )
