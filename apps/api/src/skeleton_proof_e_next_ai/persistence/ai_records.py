"""The AI attempt log (04/X6): one row per attempt, plus what it was shown, what it asked and what it said.

Append only, like the audit trail: this adapter inserts and reads, and its grant allows nothing else (02/B3, 02/D6).
Every attempt is recorded, including the ones that failed, refused or abstained; "stored is half the job: it must be
reachable" (Aegis B10), so `GET /ai/attempts/{id}` reads these rows back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.ai import Attempt
from ..domain.ids import new_id
from ..telemetry import context
from .schema import ai_attempt_context, ai_attempt_outputs, ai_attempt_requests, ai_attempts, ai_feedback


class PgAttemptLog:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def record(self, attempt: Attempt) -> None:
        # The fence (02/J6): attempts on one subject are recorded one transaction at a time, so a late run always sees
        # the newer one and `superseded` can't miss it in a race.
        subject = f"{attempt.tenant_id}:{attempt.step}:{attempt.entity}:{attempt.entity_id}"
        await self.conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(subject, 0))))
        u = attempt.usage
        await self.conn.execute(
            insert(ai_attempts).values(
                id=attempt.id,
                tenant_id=attempt.tenant_id,
                step=attempt.step,
                agent=attempt.agent,
                agent_version=attempt.agent_version,
                agent_hash=attempt.agent_hash,
                route=attempt.route,
                mode=attempt.mode.value,
                status=attempt.status.value,
                reason=attempt.reason,
                abstention=attempt.abstention,
                provider=attempt.provider,
                requested_model=attempt.requested_model,
                served_model=attempt.served_model,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                entity=attempt.entity,
                entity_id=attempt.entity_id,
                actor=attempt.actor,
                principal_kind=attempt.principal_kind,
                on_behalf_of=attempt.on_behalf_of,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_write_tokens=u.cache_write_tokens,
                cost_usd=u.cost_usd,
                price_snapshot=u.price_snapshot,
                signals=list(attempt.signals),
                correlation_id=context.correlation_id.get(),
            )
        )
        if attempt.ledger:
            await self.conn.execute(
                insert(ai_attempt_context),
                [
                    {
                        "attempt_id": attempt.id,
                        "position": n,
                        "tenant_id": attempt.tenant_id,
                        "context_id": e.id,
                        "source": e.item.source,
                        "ref": e.item.ref,
                        "trust": e.item.trust.value,
                        "data_class": e.item.data_class.value,
                        "included": e.included,
                        "drop_reason": e.drop_reason,
                        "token_estimate": e.token_estimate,
                        "signals": list(e.signals),
                        "text": e.item.text,
                    }
                    for n, e in enumerate(attempt.ledger, start=1)
                ],
            )
        await self.conn.execute(
            insert(ai_attempt_requests).values(
                attempt_id=attempt.id,
                seq=1,
                tenant_id=attempt.tenant_id,
                kind="model_call",
                body={**attempt.request, "provider": attempt.provider, "model": attempt.requested_model},
            )
        )
        raw = attempt.output_text
        await self.conn.execute(
            insert(ai_attempt_outputs).values(
                attempt_id=attempt.id,
                tenant_id=attempt.tenant_id,
                raw_text=raw,
                byte_length=len(raw.encode()) if raw is not None else None,
                result=dict(attempt.result) if attempt.result is not None else None,
            )
        )

    async def superseded(self, attempt: Attempt) -> bool:
        a = ai_attempts.c
        newer = select(a.id).where(
            a.tenant_id == attempt.tenant_id,
            a.step == attempt.step,
            a.entity == attempt.entity,
            a.entity_id == attempt.entity_id,
            a.id != attempt.id,
            or_(a.started_at > attempt.started_at, and_(a.started_at == attempt.started_at, a.id > attempt.id)),
        )
        return bool((await self.conn.execute(select(newer.exists()))).scalar_one())

    async def spent_since(self, tenant_id: UUID, since: datetime) -> Decimal:
        """Spend for the tenant since `since` (the start of the UTC day for the daily cap, 01/R2).

        Only a live call can cost money: the database refuses any other attempt with a cost (ck_attempts_spend).
        """
        total = (
            await self.conn.execute(
                select(func.coalesce(func.sum(ai_attempts.c.cost_usd), 0)).where(
                    ai_attempts.c.tenant_id == tenant_id, ai_attempts.c.started_at >= since
                )
            )
        ).scalar_one()
        return Decimal(total)

    async def feedback(self, attempt_id: UUID, tenant_id: UUID, by: str, verdict: str, correction: str | None) -> bool:
        """06/E10: a person's verdict on an attempt. False when the attempt isn't one this tenant can see."""
        seen = (await self.conn.execute(select(ai_attempts.c.id).where(ai_attempts.c.id == attempt_id))).first()
        if seen is None:
            return False
        await self.conn.execute(
            insert(ai_feedback).values(
                id=new_id(),
                attempt_id=attempt_id,
                tenant_id=tenant_id,
                given_by=by,
                verdict=verdict,
                correction=correction,
                created_at=datetime.now(UTC),
            )
        )
        return True

    async def view(self, attempt_id: UUID) -> dict[str, Any] | None:
        """Why did the assistant say that (Aegis I §03): what it was shown, asked and said, and what it cost."""
        row = (await self.conn.execute(select(ai_attempts).where(ai_attempts.c.id == attempt_id))).first()
        if row is None:
            return None
        shown = await self.conn.execute(
            select(ai_attempt_context).where(ai_attempt_context.c.attempt_id == attempt_id).order_by("position")
        )
        asked = await self.conn.execute(
            select(ai_attempt_requests.c.body).where(ai_attempt_requests.c.attempt_id == attempt_id)
        )
        said = (
            await self.conn.execute(select(ai_attempt_outputs).where(ai_attempt_outputs.c.attempt_id == attempt_id))
        ).first()
        return {
            **{k: v for k, v in row._mapping.items() if k not in ("tenant_id", "correlation_id")},
            "shown": [
                {k: v for k, v in r._mapping.items() if k not in ("attempt_id", "tenant_id", "position")} for r in shown
            ],
            "asked": [r.body for r in asked],
            "said": {"raw_text": said.raw_text, "result": said.result} if said else None,
        }
