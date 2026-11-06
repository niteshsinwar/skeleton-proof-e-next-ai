"""Running a dataset against its registered step, N times per case, and reporting it honestly (06/E2, E4, E6, E7, E11).

- Every case runs `repetitions` times and reports per run ("2 passed, 1 failed"); a live run needs at least 3.
- Results are reported per layer and per tag with their denominators, never averaged into one score.
- A run in which any attempt failed for an operational reason (provider down, timeout, AI off) is **degraded**: it is
  reported as degraded, not as a measurement ("a degraded run is not an observation").
- A fixture run proves the harness; it can never be recorded as an eval (Aegis B13).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from skeleton_proof_e_next_ai.domain.ai import Attempt, AttemptStatus, ExecutionMode
from skeleton_proof_e_next_ai.domain.principals import Principal, PrincipalKind
from skeleton_proof_e_next_ai.intelligence.steps import StepRunner

from .datasets import Dataset
from .graders import Grade, grade, pair_grades

MIN_LIVE_RUNS = 3
EVAL_TENANT = UUID(int=0xE7A1)  # eval cases run in their own tenant, never a customer's
OPERATIONAL = {
    "provider_unavailable",
    "rate_limited",
    "step_timeout",
    "ai_off",
    "provider_auth",
    "provider_bad_request",
}


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    repetition: int
    layer: str
    tags: tuple[str, ...]
    grades: tuple[Grade, ...]
    attempt: Attempt

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.grades)


@dataclass
class RunReport:
    dataset: Dataset
    mode: ExecutionMode
    repetitions: int
    started_at: datetime
    results: list[CaseResult] = field(default_factory=list)
    pairs: list[Grade] = field(default_factory=list)
    finished_at: datetime | None = None

    @property
    def degraded(self) -> bool:
        return any(r.attempt.reason in OPERATIONAL for r in self.results)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results) and all(p.passed for p in self.pairs)

    def lines(self) -> list[str]:
        out = [
            f"eval {self.dataset.key} on step {self.dataset.manifest.step}: mode {self.mode.value}, "
            f"{len(self.dataset.cases)} cases x {self.repetitions} runs"
            + (" -- DEGRADED: operational failures, so this is not a measurement" if self.degraded else "")
        ]
        by_case: dict[str, list[CaseResult]] = defaultdict(list)
        for r in self.results:
            by_case[r.case_id].append(r)
        for case_id, runs in by_case.items():
            ok = sum(r.passed for r in runs)
            failed = [g for r in runs for g in r.grades if not g.passed]
            why = f"  ({failed[0].name}: {failed[0].detail})" if failed else ""
            out.append(f"  {case_id}: {ok} passed, {len(runs) - ok} failed{why}")
        for title, key in (("layer", lambda r: [r.layer]), ("tag", lambda r: list(r.tags))):
            counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for r in self.results:
                for k in key(r):
                    counts[k][0] += r.passed
                    counts[k][1] += 1
            out.append(f"  by {title}: " + ", ".join(f"{k} {p}/{n}" for k, (p, n) in sorted(counts.items())))
        out += [f"  {p.name}: {'passed' if p.passed else 'FAILED'} ({p.detail})" for p in self.pairs]
        return out


async def run_dataset(runner: StepRunner, dataset: Dataset, *, repetitions: int, live_required: bool) -> RunReport:
    step = dataset.manifest.step
    mode = runner.gateway.mode_for(runner.agents[runner.registry.get(step).agent_key].spec.route)
    if live_required and mode is not ExecutionMode.LIVE:
        raise RuntimeError("a live eval needs the step's provider configured: the fake is a harness test, not an eval")
    if mode is ExecutionMode.LIVE and repetitions < MIN_LIVE_RUNS:
        raise RuntimeError(f"a live eval runs every case at least {MIN_LIVE_RUNS} times (06/E4)")
    principal = Principal("eval-harness", PrincipalKind.SERVICE, EVAL_TENANT, frozenset())
    report = RunReport(dataset, mode, repetitions, datetime.now(UTC))
    outcomes: dict[str, dict[str, dict[int, AttemptStatus]]] = defaultdict(lambda: defaultdict(dict))
    for case in dataset.cases:
        for n in range(1, repetitions + 1):
            result = await runner.run(step, case.step_inputs(EVAL_TENANT, f"eval:{dataset.key}"), principal)
            report.results.append(
                CaseResult(case.id, n, case.layer, tuple(case.tags), tuple(grade(case, result.attempt)), result.attempt)
            )
            if case.pair:
                outcomes[case.pair][case.id][n] = result.attempt.status
    for pair, by_case in outcomes.items():
        for n in range(1, repetitions + 1):
            report.pairs += pair_grades({f"{pair}#run{n}": {c: runs[n] for c, runs in by_case.items()}})
    report.finished_at = datetime.now(UTC)
    return report
