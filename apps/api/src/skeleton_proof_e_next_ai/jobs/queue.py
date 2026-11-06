"""The DB-backed job queue (02/J2): the in-house default behind the JobQueue contract.

queued → running → (awaiting_review →) done, or back to queued with backoff, or dead after max attempts.
A business idempotency key makes enqueue a no-op on repeats, even after the job finished. A visibility
timeout plus a reaper recovers jobs whose worker died. SKIP LOCKED lets many workers claim safely.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.ids import new_id


@dataclass(frozen=True, slots=True)
class Job:
    id: UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def enqueue(
    conn: AsyncConnection,
    kind: str,
    payload: Mapping[str, Any],
    idempotency_key: str,
    max_attempts: int = 5,
    delay: timedelta = timedelta(0),
) -> bool:
    """True if a new job was queued; False if this idempotency key was seen before (in any state)."""
    result = await conn.execute(
        text("""
        INSERT INTO jobs.jobs (id, kind, idempotency_key, payload, status, attempts, max_attempts, run_after,
                               created_at, updated_at)
        VALUES (:id, :kind, :key, CAST(:payload AS jsonb), 'queued', 0, :max, now() + :delay, now(), now())
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id"""),
        {
            "id": new_id(),
            "kind": kind,
            "key": idempotency_key,
            "payload": json.dumps(dict(payload)),
            "max": max_attempts,
            "delay": delay,
        },
    )
    return result.first() is not None  # RETURNING, not rowcount (only reliable for UPDATE/DELETE)


async def claim(conn: AsyncConnection, worker: str, visibility: timedelta) -> Job | None:
    row = (
        await conn.execute(
            text("""
        UPDATE jobs.jobs SET status = 'running', attempts = attempts + 1, locked_by = :worker,
               locked_until = now() + :visibility, updated_at = now()
        WHERE id = (SELECT id FROM jobs.jobs WHERE status = 'queued' AND run_after <= now()
                    ORDER BY run_after, id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING id, kind, payload, attempts, max_attempts"""),
            {"worker": worker, "visibility": visibility},
        )
    ).first()
    if row is None:
        return None
    return Job(
        id=row.id, kind=row.kind, payload=dict(row.payload), attempts=row.attempts, max_attempts=row.max_attempts
    )


async def complete(conn: AsyncConnection, job_id: UUID, needs_review: bool = False) -> None:
    await conn.execute(
        text("""
        UPDATE jobs.jobs SET status = :status, locked_until = NULL, locked_by = NULL, updated_at = now()
        WHERE id = :id AND status = 'running'"""),
        {"id": job_id, "status": "awaiting_review" if needs_review else "done"},
    )


async def fail(conn: AsyncConnection, job: Job, error: str, backoff: timedelta = timedelta(seconds=5)) -> str:
    """Retry with exponential backoff, or move to the visible dead letter. Returns the new status."""
    status = "dead" if job.attempts >= job.max_attempts else "queued"
    await conn.execute(
        text("""
        UPDATE jobs.jobs SET status = :status, last_error = :error, locked_until = NULL, locked_by = NULL,
               run_after = now() + :delay, updated_at = now()
        WHERE id = :id"""),
        {"status": status, "error": error[:2000], "id": job.id, "delay": backoff * (2 ** max(0, job.attempts - 1))},
    )
    return status


async def reap(conn: AsyncConnection) -> int:
    """Recover jobs whose worker vanished: past their visibility timeout. Runs on a timer, never on traffic."""
    result = await conn.execute(
        text("""
        UPDATE jobs.jobs
        SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
            last_error = coalesce(last_error, '') || ' [reaped: visibility timeout passed]',
            locked_until = NULL, locked_by = NULL, updated_at = now()
        WHERE status = 'running' AND locked_until < now()""")
    )
    return result.rowcount


async def counts(conn: AsyncConnection) -> dict[str, int]:
    rows = (await conn.execute(text("SELECT status, count(*) AS n FROM jobs.jobs GROUP BY status"))).all()
    return {r.status: r.n for r in rows}
