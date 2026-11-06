"""Outbox relay (02/J3): events written in the same transaction as the change are published after commit.

Each event becomes one job keyed by the event id, so relaying twice never duplicates work. Runs as the
worker role, which may read the outbox across tenants; the tenant travels in the job payload.
"""

from __future__ import annotations

from sqlalchemy import text

from ..persistence.db import Database
from . import queue


async def relay(db: Database, batch: int = 100) -> int:
    async with db.transaction(tenant_id=None, actor="outbox-relay", worker=True) as conn:
        rows = (
            await conn.execute(
                text("""
            SELECT id, tenant_id, aggregate, aggregate_id, sequence, kind, payload FROM app.outbox
            WHERE published_at IS NULL ORDER BY created_at, id LIMIT :batch FOR UPDATE SKIP LOCKED"""),
                {"batch": batch},
            )
        ).all()
        for r in rows:
            payload = {
                **dict(r.payload),
                "tenant_id": str(r.tenant_id),
                "aggregate_id": str(r.aggregate_id),
                "sequence": r.sequence,
            }
            await queue.enqueue(conn, r.kind, payload, idempotency_key=f"outbox:{r.id}")
            await conn.execute(text("UPDATE app.outbox SET published_at = now() WHERE id = :id"), {"id": r.id})
        return len(rows)
