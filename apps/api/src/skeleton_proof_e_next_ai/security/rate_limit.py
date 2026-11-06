"""Rate limits with GCRA (01/R2, W33): one timestamp per key, controlled bursts.

Limits are layered per principal kind and endpoint class; agents are their own traffic class (01/R3).
In-process for tier P; Postgres-backed when several instances share limits (01/AL2).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class Limit:
    per_second: float
    burst: int

    @property
    def interval(self) -> timedelta:
        return timedelta(seconds=1 / self.per_second)

    @property
    def tolerance(self) -> timedelta:
        return self.interval * (self.burst - 1)


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after_seconds: int = 0


# endpoint class -> principal kind -> limit. Humans are protected first under load (01/R3, 01/R4).
LIMITS: dict[str, dict[str, Limit]] = {
    "read": {"human": Limit(20, 60), "agent": Limit(10, 20), "service": Limit(20, 40)},
    "write": {"human": Limit(5, 20), "agent": Limit(2, 10), "service": Limit(5, 20)},
    "upload": {"human": Limit(1, 5), "agent": Limit(0.5, 2), "service": Limit(1, 5)},
}
# Webhooks carry no principal; each source gets its own limit, and failing to check it refuses (01/R2).
WEBHOOK_LIMIT = Limit(20, 100)
# What happens when the limiter's own store fails, written down per class (01/R2).
FAIL_CLOSED = {"write": True, "upload": True, "read": False}


def gcra(tat: datetime | None, now: datetime, limit: Limit) -> tuple[Decision, datetime | None]:
    """Return the decision and the new theoretical arrival time (None when denied: nothing changes)."""
    base = max(tat or now, now)
    if base - now > limit.tolerance:
        wait = (base - now - limit.tolerance).total_seconds()
        return Decision(False, max(1, int(wait + 0.999))), None
    return Decision(True), base + limit.interval


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._tat: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: Limit, now: datetime) -> Decision:
        async with self._lock:
            decision, new_tat = gcra(self._tat.get(key), now, limit)
            if new_tat is not None:
                self._tat[key] = new_tat
            return decision


class PostgresRateLimiter:
    """Atomic GCRA in one statement; the update only happens when the request is allowed."""

    def __init__(self, engine: AsyncEngine, role: str | None) -> None:
        # The role is interpolated into SET LOCAL ROLE (an identifier can't be a bound parameter), so it is checked
        # here, not trusted to have been checked elsewhere: a plain lowercase identifier, at most 63 characters.
        plain = role is None or (role.isascii() and role.isidentifier() and role == role.lower() and len(role) < 64)
        if not plain:
            raise ValueError("database roles must be plain lowercase identifiers")
        self.engine, self.role = engine, role

    async def check(self, key: str, limit: Limit, now: datetime) -> Decision:
        async with self.engine.begin() as conn:
            if self.role:
                # (reviewed: the role is a checked identifier from settings, never request input)
                # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                await conn.execute(text(f'SET LOCAL ROLE "{self.role}"'))
            row = (
                await conn.execute(
                    text("""
                INSERT INTO app.rate_limits AS r (key, tat) VALUES (:key, :now + :interval)
                ON CONFLICT (key) DO UPDATE SET tat = GREATEST(r.tat, :now) + :interval
                WHERE GREATEST(r.tat, :now) - :now <= :tolerance
                RETURNING tat"""),
                    {"key": key, "now": now, "interval": limit.interval, "tolerance": limit.tolerance},
                )
            ).first()
            if row is not None:
                return Decision(True)
            tat = (
                await conn.execute(text("SELECT tat FROM app.rate_limits WHERE key = :key"), {"key": key})
            ).scalar_one()
            decision, _ = gcra(tat, now, limit)
            return decision
