"""Agent files: `ai/agents/<agent>/v<N>.yaml`, one file per version (04/Q1–Q3, 12/NL8).

An agent file is the contract for one AI step: its job, what it must never do, who decides after it, its route (a kind
of call, never a model), what it may be shown (the grounding allowlist, 04/M4), its prompt, its output schema's name,
its budgets and the eval set that grades it. There is no prompt text anywhere else (04/Q1).

Released versions are immutable: `ai/agents/pins.json` holds each version's SHA-256, and a changed file fails
`check_pins`. A prompt change is a new version file, so a recorded run always names exactly what ran (Aegis B10, B13).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .catalogue import Catalogue, Effort

CONTEXT_VARIABLE = "context"  # the task template's slot for the data blocks; filled by the ledger, never by a caller
# Variables carry code-chosen values (a locale, a kind of record): one line, no markup. Anything a person wrote is a
# context item in its own data block, so it can never be spliced into the instructions (05/SG5).
SAFE_VARIABLE = re.compile(r"^[\w .,:;/()'-]*$")


class AgentError(ValueError):
    """An agent file is wrong; the app refuses to start (02/B5)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRule(_Strict):
    max_chars: int = Field(gt=0, le=200_000)


class Grounding(_Strict):
    max_context_tokens: int = Field(gt=0, le=900_000)
    sources: dict[str, SourceRule] = Field(min_length=1)  # the only kinds of text that may reach the provider
    on_injection_signal: Literal["flag", "block"] = "flag"  # a signal only ever raises risk (04/P4)


class Prompt(_Strict):
    system: str = Field(min_length=1)  # stable policy text: the cached prefix (04/X2)
    task: str = Field(min_length=1)  # `$context` marks where the data blocks go; `$name` for each variable


class Variable(_Strict):
    max_chars: int = Field(gt=0, le=200)


class Budgets(_Strict):
    max_seconds: float = Field(default=120, gt=0, le=900)


class EvalRef(_Strict):
    dataset: str
    version: int = Field(ge=1)


class AgentFile(_Strict):
    agent: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    version: int = Field(ge=1)
    job: str = Field(min_length=1)
    decided_after_by: Literal["code", "human"]  # who acts on the output (04/P3)
    must_never: list[str] = Field(min_length=1)
    pattern: Literal["single_call", "chain", "route", "parallel", "agent_loop", "graph"]
    route: str
    effort: Effort | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=128_000)
    grounding: Grounding
    policies: list[str] = []
    prompt: Prompt
    variables: dict[str, Variable] = {}
    output: str  # the registered output schema's name; the registry checks it matches
    links_allowed: list[str] = []  # hosts the output may link to; any other link makes it invalid (OWASP LLM05)
    tools: list[str] = []
    budgets: Budgets = Budgets()
    evals: EvalRef

    @field_validator("prompt")
    @classmethod
    def _context_slot(cls, prompt: Prompt) -> Prompt:
        if f"${CONTEXT_VARIABLE}" not in prompt.task and f"${{{CONTEXT_VARIABLE}}}" not in prompt.task:
            raise ValueError("the task must place $context, where the data blocks go")
        if "$" in prompt.system:
            raise ValueError("the system prompt is stable policy text: it takes no variables")
        return prompt


@dataclass(frozen=True, slots=True)
class Agent:
    spec: AgentFile
    sha256: str
    path: Path

    @property
    def key(self) -> str:
        return f"{self.spec.agent}@{self.spec.version}"

    def render_task(self, variables: dict[str, str], context: str) -> str:
        """Fill the task template. Every declared variable is required and checked; nothing else is accepted."""
        if set(variables) != set(self.spec.variables):
            raise AgentError(f"{self.key} takes variables {sorted(self.spec.variables)}, got {sorted(variables)}")
        for name, value in variables.items():
            if len(value) > self.spec.variables[name].max_chars or not SAFE_VARIABLE.match(value):
                raise AgentError(f"{self.key}: variable {name!r} must be one short line of plain text")
        return Template(self.spec.prompt.task).substitute({**variables, CONTEXT_VARIABLE: context})


def load_agents(root: Path, catalogue: Catalogue) -> dict[str, Agent]:
    """Every `ai/agents/<agent>/v<N>.yaml`, checked against its path and the catalogue. Keyed `agent@N`."""
    agents: dict[str, Agent] = {}
    problems: list[str] = []
    for path in sorted(root.glob("*/v*.yaml")):
        raw = path.read_bytes()
        try:
            spec = AgentFile.model_validate(yaml.safe_load(raw))
        except (yaml.YAMLError, ValidationError) as exc:
            problems.append(f"{path}: {exc}")
            continue
        if path.parent.name != spec.agent or path.stem != f"v{spec.version}":
            problems.append(f"{path}: the file must be {spec.agent}/v{spec.version}.yaml")
        if spec.route not in catalogue.routes:
            problems.append(f"{path}: unknown route {spec.route!r}")
        used = set(Template(spec.prompt.task).get_identifiers()) - {CONTEXT_VARIABLE}
        if used != set(spec.variables):
            problems.append(f"{path}: the task uses {sorted(used)} but declares {sorted(spec.variables)}")
        agent = Agent(spec, hashlib.sha256(raw).hexdigest(), path)
        agents[agent.key] = agent
    if problems:
        raise AgentError("; ".join(problems))
    return agents


def check_pins(agents: dict[str, Agent], pins_path: Path) -> list[str]:
    """Released versions never change: every agent file matches its pin, and every pin has its file."""
    pins: dict[str, str] = json.loads(pins_path.read_text(encoding="utf-8")) if pins_path.exists() else {}
    problems = [
        f'{key} is not pinned: add "{key}": "{a.sha256}" to {pins_path.name}'
        for key, a in agents.items()
        if key not in pins
    ]
    problems += [
        f"{key} changed after release: put the change in a new version file instead"
        for key, a in agents.items()
        if key in pins and pins[key] != a.sha256
    ]
    problems += [f"{key} is pinned but its file is missing" for key in pins if key not in agents]
    return problems
