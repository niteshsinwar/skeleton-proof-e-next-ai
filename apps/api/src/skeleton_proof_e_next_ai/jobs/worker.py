"""Worker and reaper loops (02/J2). Claim in one transaction, run the handler outside it, record the outcome.

No unit of work is held across the handler's external calls (02/J1). The reaper runs on its own timer,
so stuck jobs are recovered even when no traffic arrives.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import timedelta

import anyio
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from ..persistence.db import Database
from . import (
    handlers,  # noqa: F401  (importing registers every handler)
    queue,
)
from .outbox_relay import relay
from .registry import REGISTRY, Registry

log = logging.getLogger(__name__)


async def run_once(
    db: Database,
    worker: str,
    visibility: timedelta = timedelta(minutes=5),
    registry: Registry = REGISTRY,
    tracer: Tracer | None = None,
) -> bool:
    """Process at most one job. Returns False when there was nothing to do. Each job is a consumer span (07/O7)."""
    async with db.transaction(tenant_id=None, actor=worker, worker=True) as conn:
        job = await queue.claim(conn, worker, visibility)
    if job is None:
        return False
    handler = registry.get(job.kind)
    attributes = {"app.job.kind": job.kind, "app.job.id": str(job.id)}
    span_cm = (
        tracer.start_as_current_span(f"job {job.kind}", kind=SpanKind.CONSUMER, attributes=attributes)
        if tracer is not None
        else nullcontext()
    )
    with span_cm as span:
        try:
            if handler is None:
                raise LookupError(f"no handler registered for job kind '{job.kind}'")
            needs_review = await handler(job.payload, db)
        except Exception as exc:  # noqa: BLE001  (any handler failure is recorded, never swallowed)
            async with db.transaction(tenant_id=None, actor=worker, worker=True) as conn:
                status = await queue.fail(conn, job, f"{type(exc).__name__}: {exc}")
            log.warning("job failed", extra={"fields": {"job_id": str(job.id), "kind": job.kind, "status": status}})
            if span is not None:
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            return True
    async with db.transaction(tenant_id=None, actor=worker, worker=True) as conn:
        await queue.complete(conn, job.id, needs_review)
    return True


async def run_forever(
    db: Database,
    worker: str,
    poll: float = 1.0,
    reap_every: float = 30.0,
    stop: anyio.Event | None = None,
    registry: Registry = REGISTRY,
    tracer: Tracer | None = None,
) -> None:
    """Run until `stop` is set, then drain (07/O6): finish the job in hand, claim nothing new, stop the timers.

    A job still running when the platform's kill deadline passes is cut off and reaped after its visibility
    timeout, then runs again under its idempotency key (02/J2), so a hard stop loses nothing either.
    """
    stopping = stop or anyio.Event()

    async def reaper() -> None:
        while True:
            async with db.transaction(tenant_id=None, actor="reaper", worker=True) as conn:
                n = await queue.reap(conn)
            if n:
                log.warning("reaped stuck jobs", extra={"fields": {"count": n}})
            await anyio.sleep(reap_every)

    async def work() -> None:
        while not stopping.is_set():
            await relay(db)
            if not await run_once(db, worker, registry=registry, tracer=tracer):
                with anyio.move_on_after(poll):
                    await stopping.wait()

    async with anyio.create_task_group() as tg:
        tg.start_soon(reaper)
        await work()  # returns once stopping is set and the job in hand is finished
        tg.cancel_scope.cancel()
    log.info("worker drained and stopped", extra={"fields": {"worker": worker}})
