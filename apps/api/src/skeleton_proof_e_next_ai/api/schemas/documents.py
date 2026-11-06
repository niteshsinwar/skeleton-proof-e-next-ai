"""Document request and response bodies (04/X4). Sizes are bounded at the edge (02/A9)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_DOCUMENT_CHARS = 200_000  # larger sources are split by the caller; one request stays one bounded transaction


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddDocument(_In):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)
    source_ref: str = Field(min_length=1, max_length=500)  # where it came from, for provenance
    data_class: Literal["public", "internal", "confidential"] = "internal"
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)  # empty: everyone in the tenant


class DocumentOut(BaseModel):
    id: UUID
    chunks: int
    embedding_space: str | None  # None: stored for the lexical lane only, because embeddings were off or failed


class SearchDocuments(_In):
    query: str = Field(min_length=1, max_length=1000)  # in the body, so search text never lands in access logs
    limit: int = Field(default=8, ge=1, le=20)


class HitOut(BaseModel):
    document_id: UUID
    position: int
    title: str
    heading: str
    text: str
    score: float  # an order, not a confidence
    lanes: list[str]


class SearchOut(BaseModel):
    hits: list[HitOut]
    lanes: list[str]
    degraded: str | None
