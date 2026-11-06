"""Recorded runs are the evidence (06/E7; Aegis B13: "a score with no recorded run is a claim, not a measurement").

A live run is written once, insert-only, to the `eval` schema: the run with its dataset hash, agent hash, model and
summary, and one row per case per repetition. Nothing is ever updated or overwritten; a new run is a new id. A fixture
run proves the harness and is refused here, so it can never occupy a recorded run id.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import create_engine, insert, text

from skeleton_proof_e_next_ai.domain.ai import ExecutionMode
from skeleton_proof_e_next_ai.domain.ids import new_id
from skeleton_proof_e_next_ai.persistence.schema import eval_results, eval_runs

from .run import RunReport


class Recorder:
    def save(self, report: RunReport, *, agent_hash: str, git_sha: str) -> str:
        raise NotImplementedError


@dataclass
class MemoryRecorder(Recorder):
    """For the harness self-test only."""

    saved: list[RunReport] = field(default_factory=list)

    def save(self, report: RunReport, *, agent_hash: str, git_sha: str) -> str:
        self.saved.append(report)
        return f"memory-{len(self.saved)}"


class PgRecorder(Recorder):
    def __init__(self, database_url: str, app_role: str = "app_user") -> None:
        self.url, self.role = database_url, app_role

    def save(self, report: RunReport, *, agent_hash: str, git_sha: str) -> str:
        if report.mode is not ExecutionMode.LIVE:
            raise RuntimeError("only a live run is recorded as an eval; a fixture run proves the harness, nothing else")
        run_id = new_id()
        layers: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in report.results:
            layers[r.layer][0] += r.passed
            layers[r.layer][1] += 1
        first = report.results[0].attempt if report.results else None
        engine = create_engine(self.url)
        try:
            with engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{self.role}"'))
                conn.execute(
                    insert(eval_runs).values(
                        id=run_id,
                        started_at=report.started_at,
                        finished_at=report.finished_at or report.started_at,
                        mode=report.mode.value,
                        dataset=report.dataset.manifest.dataset,
                        dataset_version=report.dataset.manifest.version,
                        dataset_sha256=report.dataset.manifest.cases_sha256,
                        step=report.dataset.manifest.step,
                        agent_hash=agent_hash,
                        route=first.route if first else "",
                        model=first.served_model if first else None,
                        repetitions=report.repetitions,
                        git_sha=git_sha,
                        cases=len(report.dataset.cases),
                        passed=sum(r.passed for r in report.results),
                        failed=sum(not r.passed for r in report.results),
                        degraded=report.degraded,
                        by_layer={k: {"passed": p, "total": n} for k, (p, n) in sorted(layers.items())},
                    )
                )
                conn.execute(
                    insert(eval_results),
                    [
                        {
                            "run_id": run_id,
                            "case_id": r.case_id,
                            "repetition": r.repetition,
                            "layer": r.layer,
                            "tags": list(r.tags),
                            "passed": r.passed,
                            "grades": [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in r.grades],
                            "status": r.attempt.status.value,
                            "reason": r.attempt.reason,
                            "cost_usd": r.attempt.usage.cost_usd,
                            "output_sha256": hashlib.sha256((r.attempt.output_text or "").encode()).hexdigest(),
                            "served_model": r.attempt.served_model,
                        }
                        for r in report.results
                    ],
                )
        finally:
            engine.dispose()
        return str(run_id)


def summary_json(report: RunReport) -> str:
    return json.dumps({"lines": report.lines(), "passed": report.passed, "degraded": report.degraded}, indent=2)
