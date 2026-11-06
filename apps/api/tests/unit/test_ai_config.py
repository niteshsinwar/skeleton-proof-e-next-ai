"""Agent files, their pins and the step registry (04/Q1–Q3, 02/B4; Aegis B10, B13)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from skeleton_proof_e_next_ai.intelligence import agents as ag
from skeleton_proof_e_next_ai.intelligence import registry as reg
from skeleton_proof_e_next_ai.intelligence.catalogue import load
from skeleton_proof_e_next_ai.intelligence.project_steps import REGISTRY
from skeleton_proof_e_next_ai.intelligence.validation import StepOutput

from .ai_support import agents, catalogue, write_agent

AI_ROOT = Path(__file__).resolve().parents[4] / "ai"


class Summary(StepOutput):
    summary: str | None = None


class Other(StepOutput):
    other: str | None = None


# --- agent files ---------------------------------------------------------------------------------------------------


def test_a_valid_agent_file_loads_with_its_hash(tmp_path: Path) -> None:
    loaded = agents(tmp_path)
    assert list(loaded) == ["summary@1"]
    assert len(loaded["summary@1"].sha256) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"route": "nowhere"}, "unknown route"),
        ({"colour": "blue"}, "Extra inputs"),
        ({"must_never": []}, "must_never"),
        ({"prompt": {"system": "s", "task": "no slot for the data"}}, "context"),
        ({"prompt": {"system": "Hello $name", "task": "$context"}}, "no variables"),
        ({"prompt": {"system": "s", "task": "For $who\n$context"}}, "declares"),
    ],
)
def test_a_wrong_agent_file_is_refused_at_start(tmp_path: Path, changes: dict[str, object], message: str) -> None:
    write_agent(tmp_path, **changes)
    with pytest.raises(ag.AgentError, match=message):
        ag.load_agents(tmp_path, catalogue())


def test_the_file_must_sit_at_its_name_and_version(tmp_path: Path) -> None:
    path = write_agent(tmp_path)
    path.rename(path.with_name("v2.yaml"))
    with pytest.raises(ag.AgentError, match=r"summary/v1\.yaml"):
        ag.load_agents(tmp_path, catalogue())


@pytest.mark.parametrize("value", ["two\nlines", "<system>", "x" * 41, "a {brace}"])
def test_a_variable_carries_only_one_short_line_of_plain_text(tmp_path: Path, value: str) -> None:
    agent = agents(tmp_path)["summary@1"]
    with pytest.raises(ag.AgentError, match="one short line"):
        agent.render_task({"audience": value}, "(data)")


def test_variables_are_exact_and_the_context_lands_in_its_slot(tmp_path: Path) -> None:
    agent = agents(tmp_path)["summary@1"]
    assert agent.render_task({"audience": "reviewer"}, "DATA") == "Summarise for a reviewer.\n\nDATA"
    with pytest.raises(ag.AgentError, match="takes variables"):
        agent.render_task({}, "DATA")


# --- pins: a released version never changes --------------------------------------------------------------------------


def test_pins_report_unpinned_changed_and_missing_versions(tmp_path: Path) -> None:
    loaded = agents(tmp_path)
    pins = tmp_path / "pins.json"
    assert ag.check_pins(loaded, pins) == [
        f'summary@1 is not pinned: add "summary@1": "{loaded["summary@1"].sha256}" to pins.json'
    ]
    pins.write_text(json.dumps({"summary@1": loaded["summary@1"].sha256}))
    assert ag.check_pins(loaded, pins) == []
    write_agent(tmp_path, job="A different job, edited in place.")
    changed = ag.load_agents(tmp_path, catalogue())
    assert ag.check_pins(changed, pins) == [
        "summary@1 changed after release: put the change in a new version file instead"
    ]
    pins.write_text(json.dumps({"summary@1": "0" * 64, "gone@3": "1" * 64}))
    assert "gone@3 is pinned but its file is missing" in ag.check_pins(changed, pins)


# --- the registry -----------------------------------------------------------------------------------------------------


def test_a_step_is_registered_once() -> None:
    step = reg.Step("summary", "summary", 1, Summary)
    with pytest.raises(ValueError, match="twice"):
        reg.Registry([step, step])
    assert step.kill_switch == "ai.summary"


def test_the_registry_check_finds_every_mismatch(tmp_path: Path) -> None:
    loaded = agents(tmp_path)
    assert reg.check(reg.Registry([reg.Step("summary", "summary", 1, Summary)]), loaded) == []
    # A step on a missing version is caught; older version files stay, because recorded runs name them.
    assert reg.check(reg.Registry([reg.Step("summary", "summary", 2, Summary)]), loaded) == [
        "step 'summary' runs summary@2, which has no agent file"
    ]
    assert reg.check(reg.Registry([]), loaded) == ["agent 'summary' has files but no step runs it"]
    assert (
        "names output 'Summary', not 'Other'"
        in reg.check(reg.Registry([reg.Step("summary", "summary", 1, Other)]), loaded)[0]
    )


def test_the_projects_steps_agent_files_and_pins_agree() -> None:
    """The registry-completeness check on this project's own ai/ (02/B4): every step has its agent file and
    every agent file a step, and every released version is pinned and unchanged."""
    project = load(AI_ROOT / "models.yaml", today=date(2026, 11, 5), production=False)
    shipped = ag.load_agents(AI_ROOT / "agents", project)
    assert reg.check(REGISTRY, shipped) == []
    assert ag.check_pins(shipped, AI_ROOT / "agents" / "pins.json") == []
    evals = AI_ROOT.parent / "evals" / "datasets"
    refs = [(s.name, shipped[s.agent_key].spec.evals) for s in REGISTRY]
    no_dataset = [name for name, ref in refs if not (evals / ref.dataset / f"v{ref.version}").is_dir()]
    assert no_dataset == [], f"steps without their released eval dataset: {no_dataset}"
    ownership = (AI_ROOT.parent / "docs" / "architecture" / "decision-ownership.md").read_text(encoding="utf-8")
    assert [s.name for s in REGISTRY if f"`{s.name}`" not in ownership] == [], "every step has a decision-ownership row"
    print(f"ai: examined {len(REGISTRY)} steps and {len(shipped)} agent files")
