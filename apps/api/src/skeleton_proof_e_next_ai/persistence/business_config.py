"""Business configuration: versioned, effective-dated data with a strict loader (02/B5, 02/D9).

Unknown keys raise. A version that records have used is never edited: add a new version with a later
effective_from instead.
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkItemPolicy(_Strict):
    version: int = Field(ge=1)
    effective_from: date
    max_title_length: int = Field(ge=1, le=200)


class BusinessConfig(_Strict):
    work_items: list[WorkItemPolicy] = Field(min_length=1)

    def work_item_policy(self, on: date) -> WorkItemPolicy:
        current = [p for p in self.work_items if p.effective_from <= on]
        if not current:
            raise LookupError(f"No work-item policy is in force on {on.isoformat()}.")
        return max(current, key=lambda p: (p.effective_from, p.version))


def load(directory: Path) -> BusinessConfig:
    with (directory / "business.toml").open("rb") as f:
        return BusinessConfig.model_validate(tomllib.load(f))
