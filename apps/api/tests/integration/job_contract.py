"""The job contract (02/J2): what any queue must do to be adopted (13/SK6). Implementation-neutral.

Any adapter that satisfies QueueUnderTest can be run through every scenario here: the in-house queue
(test_jobs.py) and candidate libraries (the skeleton's Procrastinate spike) are judged by the same checks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class QueueUnderTest(Protocol):
    async def enqueue(self, kind: str, payload: dict[str, Any], key: str, max_attempts: int) -> bool: ...
    async def run_once(self, handler: Handler) -> bool: ...
    async def crash_after_claim(self) -> None: ...  # a worker claims one job, then dies without finishing
    async def make_due(self) -> None: ...  # test clock: everything scheduled for later becomes due now
    async def reap(self) -> int: ...
    async def counts(self) -> dict[str, int]: ...  # normalised: queued, running, done, dead


async def _ok(payload: dict[str, Any]) -> None:
    return None


async def scenario_idempotent_enqueue_even_after_done(q: QueueUnderTest) -> None:
    assert await q.enqueue("k", {"n": 1}, "biz-key-1", 3) is True
    assert await q.enqueue("k", {"n": 1}, "biz-key-1", 3) is False
    assert await q.run_once(_ok) is True
    assert await q.enqueue("k", {"n": 1}, "biz-key-1", 3) is False, "a finished job's key must still deduplicate"
    assert (await q.counts()).get("done") == 1


async def scenario_bounded_retries_end_in_a_visible_dead_letter(q: QueueUnderTest) -> None:
    calls = 0

    async def boom(payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream down")

    await q.enqueue("k", {}, "biz-key-2", 3)
    for _ in range(5):
        await q.make_due()
        await q.run_once(boom)
    assert calls == 3, f"expected exactly 3 attempts, got {calls}"
    assert (await q.counts()).get("dead") == 1, "exhausted jobs must be visible, not silently dropped"


async def scenario_crashed_worker_is_recovered_by_the_reaper(q: QueueUnderTest) -> None:
    seen: list[dict[str, Any]] = []

    async def record(payload: dict[str, Any]) -> None:
        seen.append(payload)

    await q.enqueue("k", {"n": 3}, "biz-key-3", 3)
    await q.crash_after_claim()
    assert await q.reap() == 1, "the reaper must recover a job whose worker vanished"
    await q.make_due()
    assert await q.run_once(record) is True
    assert seen == [{"n": 3}]
    assert (await q.counts()).get("done") == 1


async def scenario_nothing_to_do_returns_false(q: QueueUnderTest) -> None:
    assert await q.run_once(_ok) is False


SCENARIOS = [
    scenario_idempotent_enqueue_even_after_done,
    scenario_bounded_retries_end_in_a_visible_dead_letter,
    scenario_crashed_worker_is_recovered_by_the_reaper,
    scenario_nothing_to_do_returns_false,
]
