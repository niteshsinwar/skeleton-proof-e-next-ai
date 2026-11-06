"""The in-house queue against the job contract, plus outbox relay and concurrency (02/J2, 02/J3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import anyio
import pytest
from sqlalchemy import text

from skeleton_proof_e_next_ai.jobs import queue
from skeleton_proof_e_next_ai.jobs.outbox_relay import relay
from skeleton_proof_e_next_ai.jobs.registry import Registry
from skeleton_proof_e_next_ai.jobs.worker import run_forever, run_once
from skeleton_proof_e_next_ai.persistence.db import Database

from .job_contract import SCENARIOS, Handler

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


class InHouseQueue:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def enqueue(self, kind: str, payload: dict[str, Any], key: str, max_attempts: int) -> bool:
        async with self.db.transaction(tenant_id=None, actor="test", worker=True) as conn:
            return await queue.enqueue(conn, kind, payload, key, max_attempts)

    async def run_once(self, handler: Handler) -> bool:
        reg = Registry()

        async def adapt(payload: dict[str, Any], db: Database) -> bool:
            await handler(payload)
            return False

        for kind in ("k",):
            reg.handler(kind)(adapt)
        return await run_once(self.db, "w1", registry=reg)

    async def crash_after_claim(self) -> None:
        async with self.db.transaction(tenant_id=None, actor="test", worker=True) as conn:
            assert await queue.claim(conn, "doomed", timedelta(seconds=-1)) is not None  # already expired

    async def make_due(self) -> None:
        async with self.db.engine.begin() as conn:
            await conn.execute(text("UPDATE jobs.jobs SET run_after = now() WHERE status = 'queued'"))

    async def reap(self) -> int:
        async with self.db.transaction(tenant_id=None, actor="test", worker=True) as conn:
            return await queue.reap(conn)

    async def counts(self) -> dict[str, int]:
        async with self.db.transaction(tenant_id=None, actor="test", worker=True) as conn:
            return await queue.counts(conn)


@pytest.fixture
async def db(migrated: str) -> AsyncIterator[Database]:
    database = Database(migrated, "app_user", "app_worker")
    async with database.engine.begin() as conn:
        await conn.execute(text("TRUNCATE jobs.jobs, app.outbox"))
    yield database
    await database.dispose()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.__name__)
async def test_in_house_queue_meets_the_job_contract(db: Database, scenario: Any) -> None:
    await scenario(InHouseQueue(db))


async def test_concurrent_workers_never_run_a_job_twice(db: Database) -> None:
    calls = 0
    reg = Registry()

    @reg.handler("slow")
    async def slow(payload: dict[str, Any], _: Database) -> bool:
        nonlocal calls
        calls += 1
        await anyio.sleep(0.2)
        return False

    async with db.transaction(tenant_id=None, actor="t", worker=True) as conn:
        await queue.enqueue(conn, "slow", {}, "one-job")
    async with anyio.create_task_group() as tg:
        for name in ("w1", "w2", "w3"):
            tg.start_soon(run_once, db, name, timedelta(minutes=1), reg)
    assert calls == 1, "SKIP LOCKED must hand a job to exactly one worker"


async def test_a_stopped_worker_finishes_the_job_in_hand_and_claims_no_more(db: Database) -> None:
    """07/O6: drain before stopping. SIGTERM sets `stop`; the job in hand completes, the next one stays queued."""
    started, release, finished = anyio.Event(), anyio.Event(), anyio.Event()
    ran: list[str] = []
    reg = Registry()

    @reg.handler("long")
    async def long(payload: dict[str, Any], _: Database) -> bool:
        ran.append(payload["n"])
        started.set()
        await release.wait()
        return False

    async with db.transaction(tenant_id=None, actor="t", worker=True) as conn:
        await queue.enqueue(conn, "long", {"n": "first"}, "drain-1")
        await queue.enqueue(conn, "long", {"n": "second"}, "drain-2")
    stop = anyio.Event()

    async def worker() -> None:
        await run_forever(db, "w-drain", poll=0.05, stop=stop, registry=reg)
        finished.set()

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(worker)
            await started.wait()
            stop.set()
            await anyio.sleep(0.3)
            assert not finished.is_set(), "the worker stopped with a job still in hand"
            release.set()
            await finished.wait()
    assert ran == ["first"], "after the stop signal no new job is claimed"
    async with db.transaction(tenant_id=None, actor="t", worker=True) as conn:
        counts = await queue.counts(conn)
    assert counts.get("queued") == 1 and sum(counts.values()) == 2, counts


async def test_outbox_relay_publishes_each_event_once(db: Database) -> None:
    async with db.engine.begin() as conn:
        await conn.execute(
            text("""INSERT INTO app.outbox (id, tenant_id, aggregate, aggregate_id, sequence, kind, payload, created_at)
            VALUES (gen_random_uuid(), '00000000-0000-0000-0000-00000000000a', 'work_item', gen_random_uuid(), 1,
                    'work_item.created', '{"id": "x"}', now())""")
        )
    assert await relay(db) == 1
    assert await relay(db) == 0, "a published event is never relayed twice"
    async with db.transaction(tenant_id=None, actor="t", worker=True) as conn:
        assert await queue.counts(conn) == {"queued": 1}
