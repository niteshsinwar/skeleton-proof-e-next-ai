"""Every released dataset, run LIVE against its registered step (06/E4, E7, E8). Run with `make eval`.

Without EVAL_LIVE=1 the suite stops with an error instead of passing: a gate that can't fail is no gate, and the fake
provider is a harness test, never an eval (06/T4). Every run is recorded; a degraded run or a regression fails.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from skeleton_proof_e_next_ai.api.app import build_ai
from skeleton_proof_e_next_ai.config.settings import Settings

from harness.datasets import Dataset, all_releases
from harness.recording import PgRecorder
from harness.run import run_dataset

ROOT = Path(__file__).resolve().parent
RELEASES = all_releases(ROOT / "datasets")

pytestmark = [pytest.mark.anyio, pytest.mark.eval]


def _live_store() -> str:
    if os.environ.get("EVAL_LIVE") != "1":
        pytest.exit(
            "eval: set EVAL_LIVE=1 to call the real model (it costs money); `make eval-selftest` tests the harness", 4
        )
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        pytest.exit("eval: set APP_DATABASE_URL; a score with no recorded run is a claim, not a measurement (06/E7)", 4)
    return url


def _git_sha() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return r.stdout.strip() or "unknown"


def test_there_is_something_to_evaluate() -> None:
    _live_store()
    assert RELEASES, "no dataset release under evals/datasets: an eval that examined nothing does not pass (10/H18)"


@pytest.mark.parametrize("dataset", RELEASES, ids=[d.key for d in RELEASES])
async def test_a_released_dataset_holds_on_the_real_model(dataset: Dataset, request: pytest.FixtureRequest) -> None:
    url = _live_store()
    runner, _ = build_ai(Settings())
    report = await run_dataset(runner, dataset, repetitions=request.config.getoption("--runs"), live_required=True)
    print("\n" + "\n".join(report.lines()))
    agent_hash = runner.agents[runner.registry.get(dataset.manifest.step).agent_key].sha256
    run_id = PgRecorder(url).save(report, agent_hash=agent_hash, git_sha=_git_sha())
    assert not report.degraded, f"run {run_id} is degraded (operational failures): it is not a measurement"
    assert report.passed, f"run {run_id} has failures; regressions block (06/E8)"
