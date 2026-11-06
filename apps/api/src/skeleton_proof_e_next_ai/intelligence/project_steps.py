"""This project's AI steps (02/B4): one place declares them all.

`/ai-step` adds a step here, with its agent file in ai/agents/, its output schema, its eval dataset in
evals/datasets/ and its row in docs/architecture/decision-ownership.md; a test refuses a step missing any of them.
"""

from __future__ import annotations

from . import work_item_brief  # EXAMPLE SLICE: delete with the slice
from .registry import Registry, Step

STEPS: tuple[Step, ...] = (work_item_brief.STEP,)
REGISTRY = Registry(STEPS)
