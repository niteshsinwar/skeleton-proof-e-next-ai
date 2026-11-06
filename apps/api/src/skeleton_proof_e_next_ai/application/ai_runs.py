"""Running an AI step from a use case: the shape every feature follows (04/P5, 01/R5, 02/J1, 05/SG11).

    1. In the first transaction: load and authorise what the step may see, then `admit` (kill switches, daily budget).
    2. With no transaction open: `runner.run(...)`, which never raises for a model failure; it returns a result.
    3. In a second transaction: `record` the attempt (always, whatever the outcome), re-check the versions the step
       read, and write the feature's own outcome from `result.value` only if `result.succeeded` and `record` said the
       run is still current: late output from a superseded run is fenced (02/J6).

The product keeps working when the AI doesn't: a feature reads `succeeded` and shows its own fallback, never a
guessed answer. Nothing here decides anything a model said; the feature's use case does, in code (04/P6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ..domain.ai import GLOBAL_KILL_SWITCH, AIBudgetSpent, AIUnavailable, StepResult, kill_switch
from ..domain.ports import AttemptLog, FlagPort
from ..domain.principals import Principal


@dataclass(frozen=True, slots=True)
class Ports:
    attempts: AttemptLog
    flags: FlagPort


async def admit(ports: Ports, principal: Principal, step: str, *, daily_cap_usd: Decimal, now: datetime) -> None:
    """Refuse before spending anything: switched off for this tenant, or today's budget spent (01/R2, 07/O19)."""
    tenant = principal.tenant_id
    if not await ports.flags.enabled(GLOBAL_KILL_SWITCH, tenant) or not await ports.flags.enabled(
        kill_switch(step), tenant
    ):
        raise AIUnavailable("The assistant is switched off here for now.", retry_after=300)
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if await ports.attempts.spent_since(tenant, day_start) >= daily_cap_usd:
        tomorrow = day_start + timedelta(days=1)
        raise AIBudgetSpent(
            "Today's assistant budget is used up; it resets at midnight UTC.",
            retry_after=max(1, int((tomorrow - now).total_seconds())),
        )


async def record(ports: Ports, result: StepResult) -> bool:
    """Every attempt is recorded: succeeded, abstained, invalid, refused or failed (04/X6).

    Returns whether the run is still current: False when a run of the same step on the same subject that started
    later was recorded first. The caller then uses none of this output (02/J6).
    """
    await ports.attempts.record(result.attempt)
    return not await ports.attempts.superseded(result.attempt)
