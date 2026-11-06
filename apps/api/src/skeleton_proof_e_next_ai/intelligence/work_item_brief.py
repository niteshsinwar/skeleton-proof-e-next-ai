"""EXAMPLE SLICE: an approver's brief on a work item. Copy its shape for a real step, then delete it with the slice.

The model summarises; code checks every point against the record and decides nothing (04/P3, P6). A brief whose
points don't verify is rejected whole; a brief with no point at all is an abstention, never an empty "all fine".
"""

from __future__ import annotations

from pydantic import Field

from .ledger import Ledger
from .registry import Step
from .validation import Citation, StepOutput


class BriefPoint(StepOutput):
    text: str = Field(description="One thing the approver should know, in a short sentence.")
    cite: Citation


class WorkItemBrief(StepOutput):
    points: tuple[BriefPoint, ...] = Field(default=(), description="At most five points, each citing the record.")


def needs_a_point(output: StepOutput, _: Ledger) -> str | None:
    """A judgement no verified claim supports is an abstention (04/Q5)."""
    if isinstance(output, WorkItemBrief) and not output.points:
        return "abstain:The record gives nothing to brief on."
    if isinstance(output, WorkItemBrief) and len(output.points) > 5:
        return "too_many_points"
    return None


STEP = Step("work_item_brief", "work-item-brief", 1, WorkItemBrief, (needs_a_point,))
