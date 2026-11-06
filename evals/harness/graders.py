"""Graders: code first, then judges only once calibrated (06/E5, EL3).

Each grader returns a named pass or fail with what it saw, so a failure message says why (06/T7: the proof is the
message). An LLM judge may inform a report, but `judge_may_gate` refuses to let it gate anything until its rubric's
calibration record shows agreement with human labels (Cohen's κ ≥ 0.6 on at least 30 labelled cases). A judge is never
independent human review (Aegis I §00).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from skeleton_proof_e_next_ai.domain.ai import Attempt, AttemptStatus

from .datasets import Case

MIN_KAPPA = 0.6
MIN_LABELS = 30


@dataclass(frozen=True, slots=True)
class Grade:
    name: str
    passed: bool
    detail: str


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _cited(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        if set(value) == {"source", "quote"} and isinstance(value["source"], str):
            found.add(value["source"])
        for v in value.values():
            found |= _cited(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            found |= _cited(v)
    return found


def grade(case: Case, attempt: Attempt) -> list[Grade]:
    expect = case.expect
    grades = [
        Grade(
            "status",
            attempt.status is expect.status,
            f"expected {expect.status.value}, got {attempt.status.value}"
            + (f" ({attempt.reason})" if attempt.reason else ""),
        )
    ]
    if expect.status is AttemptStatus.SUCCEEDED and attempt.result is not None:
        text = " ".join(_strings(attempt.result)).lower()
        missing = [p for p in expect.must_include if p.lower() not in text]
        grades.append(Grade("must_include", not missing, f"missing {missing}" if missing else "all present"))
        cited = _cited(attempt.result)
        uncited = [c for c in expect.cites if c not in cited]
        grades.append(Grade("cites", not uncited, f"did not cite {uncited}" if uncited else f"cited {sorted(cited)}"))
    if expect.must_not_include:
        seen = " ".join([*_strings(attempt.result or {}), attempt.output_text or ""]).lower()
        present = [p for p in expect.must_not_include if p.lower() in seen]
        grades.append(Grade("must_not_include", not present, f"contained {present}" if present else "none present"))
    if expect.max_cost_usd is not None:
        cost = attempt.usage.cost_usd
        ok = cost is not None and cost <= Decimal(str(expect.max_cost_usd))
        grades.append(Grade("cost", ok, f"cost {cost} against a ceiling of {expect.max_cost_usd}"))
    return grades


def pair_grades(outcomes: Mapping[str, Mapping[str, AttemptStatus]]) -> list[Grade]:
    """Matched pairs (04/H3): the two cases of a pair get the same outcome on every run. `outcomes[pair][case]`."""
    return [
        Grade(
            f"pair:{pair}",
            len(set(by_case.values())) == 1,
            f"outcomes {dict((k, v.value) for k, v in by_case.items())}",
        )
        for pair, by_case in sorted(outcomes.items())
    ]


type Choice = Literal["first", "second", "tie"]
# A pairwise judge: (rubric, first answer, second answer) -> which one the rubric prefers. Any provider behind it.
type PairwiseJudge = Callable[[str, str, str], Awaitable[str]]
_SWAPPED: dict[str, str] = {"first": "second", "second": "first", "tie": "tie"}


@dataclass(frozen=True, slots=True)
class Preference:
    verdict: Literal["a", "b", "tie", "inconsistent"]
    detail: str


async def judge_both_orders(judge: PairwiseJudge, rubric: str, a: str, b: str) -> Preference:
    """06/E5: a judge sees every pair in both orders. A verdict that changes with the order is position bias, not a
    preference, so it counts for neither answer."""
    one, two = await judge(rubric, a, b), await judge(rubric, b, a)
    if one not in _SWAPPED or two not in _SWAPPED:
        return Preference("inconsistent", f"the judge answered {one!r} and {two!r}; expected first, second or tie")
    if _SWAPPED[two] != one:
        return Preference("inconsistent", f"position bias: {one} with a first, {two} with b first")
    verdict: Literal["a", "b", "tie"] = "a" if one == "first" else "b" if one == "second" else "tie"
    return Preference(verdict, f"{verdict} in both orders")


@dataclass(frozen=True, slots=True)
class Calibration:
    rubric: str
    judge_route: str
    labelled_cases: int
    kappa: float
    measured_on: date


def judge_may_gate(record: Path) -> tuple[bool, str]:
    """A judge gates only with a calibration record showing κ ≥ 0.6 against human labels on ≥ 30 cases (06/E5)."""
    if not record.is_file():
        return False, f"no calibration record at {record}: the judge may inform, not gate"
    raw = json.loads(record.read_text(encoding="utf-8"))
    cal = Calibration(
        raw["rubric"],
        raw["judge_route"],
        int(raw["labelled_cases"]),
        float(raw["kappa"]),
        date.fromisoformat(raw["measured_on"]),
    )
    if cal.labelled_cases < MIN_LABELS:
        return False, f"only {cal.labelled_cases} human-labelled cases; {MIN_LABELS} are needed"
    if cal.kappa < MIN_KAPPA:
        return False, f"κ = {cal.kappa:.2f} against human labels; {MIN_KAPPA} is needed"
    return True, f"κ = {cal.kappa:.2f} on {cal.labelled_cases} cases, measured {cal.measured_on}"
