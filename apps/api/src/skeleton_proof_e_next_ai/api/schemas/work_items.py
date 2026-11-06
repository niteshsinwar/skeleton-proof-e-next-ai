"""EXAMPLE SLICE — contracts. Strict in (unknown fields rejected), explicit allowlist out (02/A8)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...domain.work_items import WorkItem


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateWorkItem(_In):
    title: str = Field(min_length=1, max_length=200)


class Decide(_In):
    reason: str | None = Field(default=None, max_length=2000)


class WorkItemOut(BaseModel):
    id: UUID
    title: str
    state: str
    version: int
    created_by: str
    created_at: datetime
    submitted_by: str | None
    decided_by: str | None
    decision_reason: str | None
    # Names to show for created_by and decided_by (03/F16); null when the token carried no name.
    created_by_name: str | None
    decided_by_name: str | None

    @classmethod
    def of(cls, item: WorkItem) -> WorkItemOut:
        return cls(
            id=item.id,
            title=item.title,
            state=item.state.value,
            version=item.version,
            created_by=item.created_by,
            created_at=item.created_at,
            submitted_by=item.submitted_by,
            decided_by=item.decided_by,
            decision_reason=item.decision_reason,
            created_by_name=item.created_by_name,
            decided_by_name=item.decided_by_name,
        )


class WorkItemPage(BaseModel):
    items: list[WorkItemOut]
    next_cursor: str | None


class SetFlag(_In):
    enabled: bool
    reason: str = Field(min_length=1, max_length=500)


class ChangeDecision(_In):
    reason: str = Field(min_length=1, max_length=500)


class MeOut(BaseModel):
    """Who the caller is and what they may do, from the API's own grants (02/Z5)."""

    subject: str
    name: str | None
    kind: str
    roles: list[str]
    capabilities: list[str]


class ChangeRole(_In):
    role: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=500)


class UploadOut(BaseModel):
    id: UUID
    media_type: str
    size_bytes: int
