"""The step registry: one place declares every AI step (02/B4; Aegis B10 "a step added by hand to none of three lists").

A step joins an agent file (the contract and prompt) to the code that checks its output: the output schema and its
verifiers. Add a step with `/ai-step`; `check` (run by a test and at start) refuses a step whose agent file is
missing or names another output, and an agent file no step runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ..domain.ai import kill_switch
from .agents import Agent
from .tools import REGISTRY as TOOL_REGISTRY
from .tools import ToolRegistry
from .validation import StepOutput, Verifier

TOOL_RESULT_SOURCE = "tool_result"  # an agent that uses tools must let their results into its grounding


@dataclass(frozen=True, slots=True)
class Step:
    name: str  # snake_case, stable: it keys records, the kill switch and the eval dataset
    agent: str
    version: int
    output: type[StepOutput]
    verifiers: tuple[Verifier, ...] = ()

    @property
    def agent_key(self) -> str:
        return f"{self.agent}@{self.version}"

    @property
    def kill_switch(self) -> str:
        """The flag that turns this step off per tenant, audited (05/SG11). `ai` turns every step off."""
        return kill_switch(self.name)


class Registry:
    def __init__(self, steps: Iterable[Step]) -> None:
        self._steps: dict[str, Step] = {}
        for step in steps:
            if step.name in self._steps:
                raise ValueError(f"step {step.name!r} is registered twice")
            self._steps[step.name] = step

    def get(self, name: str) -> Step:
        if name not in self._steps:
            raise KeyError(f"no AI step named {name!r}")
        return self._steps[name]

    def __iter__(self) -> Iterator[Step]:
        return iter(self._steps.values())

    def __len__(self) -> int:
        return len(self._steps)


def check(registry: Registry, agents: dict[str, Agent], tools: ToolRegistry = TOOL_REGISTRY) -> list[str]:
    problems: list[str] = []
    for each in agents.values():
        unknown = [t for t in each.spec.tools if tools.get(t) is None]
        if unknown:
            problems.append(f"{each.key} lists unknown tools {unknown}")
        if each.spec.tools and TOOL_RESULT_SOURCE not in each.spec.grounding.sources:
            problems.append(f"{each.key} uses tools but its grounding doesn't allow {TOOL_RESULT_SOURCE!r}")
    for step in registry:
        agent = agents.get(step.agent_key)
        if agent is None:
            problems.append(f"step {step.name!r} runs {step.agent_key}, which has no agent file")
        elif agent.spec.output != step.output.__name__:
            problems.append(
                f"step {step.name!r}: {step.agent_key} names output {agent.spec.output!r}, not {step.output.__name__!r}"
            )
    run = {step.agent for step in registry}
    problems += [
        f"agent {name!r} has files but no step runs it"
        for name in sorted({a.spec.agent for a in agents.values()} - run)
    ]
    return problems
