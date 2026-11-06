"""Retrieval's value objects (04/X4–X5, 02/D11): documents in chunks, searched by the people allowed to see them.

Who may see a document is part of the document (`allowed_roles`: empty means everyone in its tenant), so search filters
by tenant and role **before** ranking anything (04/X4, 02/Z11). An embedding belongs to a named space (model and
dimensions): chunks from another space are never compared with a query from this one (re-index blue/green, 04/X4).
Live state (status, balances, what is in force) is queried from the record, never retrieved (02/D12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .ai import ContextItem, DataClass, ExecutionMode, Trust
from .errors import InvariantViolated

type ChunkKey = tuple[UUID, int]  # (document id, chunk position)

CONTEXT_SOURCE = "document.chunk"  # the source name an agent file allowlists to be shown retrieved text (04/M4)


@dataclass(frozen=True, slots=True)
class Document:
    id: UUID
    tenant_id: UUID
    title: str
    source_ref: str  # where it came from (an upload id, a URL, a system record), for provenance
    data_class: DataClass
    allowed_roles: tuple[str, ...]  # empty: everyone in the tenant; else only holders of one of these roles
    version: int
    created_by: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise InvariantViolated("A document has a title.")
        if self.data_class is DataClass.REGULATED:
            raise InvariantViolated("Regulated data is not indexed without an ADR naming the agreement (05/SG9).")

    def visible_to(self, roles: frozenset[str]) -> bool:
        return not self.allowed_roles or bool(set(self.allowed_roles) & roles)


@dataclass(frozen=True, slots=True)
class Chunk:
    position: int
    heading: str  # the heading path it sits under, so a citation can say where in the document it is
    text: str


class EmbedTask(StrEnum):
    DOCUMENT = "document"  # text being stored
    QUERY = "query"  # what someone is searching for; models embed the two differently


@dataclass(frozen=True, slots=True)
class Embedded:
    """What one embedding call produced. `vectors` is None when it failed or AI is off; `failure` then says why."""

    vectors: tuple[tuple[float, ...], ...] | None
    space: str | None
    mode: ExecutionMode
    failure: str | None = None
    attempts: int = 0

    def __post_init__(self) -> None:
        if (self.vectors is None) == (self.failure is None):
            raise InvariantViolated("An embedding result has vectors or a failure, never both or neither.")
        if self.vectors is not None and self.space is None:
            raise InvariantViolated("Vectors always name the space they belong to (04/X4).")

    @staticmethod
    def off(reason: str = "ai_off") -> Embedded:
        return Embedded(None, None, ExecutionMode.AI_OFF, reason)


@dataclass(frozen=True, slots=True)
class SearchScope:
    """Who is searching: the filter applied before anything is ranked (04/X4, 02/Z11)."""

    tenant_id: UUID
    roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class SearchHit:
    document_id: UUID
    position: int
    title: str
    heading: str
    text: str
    data_class: DataClass
    score: float  # the fused rank score: an order, never a confidence (no threshold abstains, 04/X4)
    lanes: tuple[str, ...]  # which lanes found it: "lexical", "vector"

    def as_context(self, tenant_id: UUID) -> ContextItem:
        """Retrieved text enters a prompt as untrusted data that can never drive an action (05/SG5, 04/X1)."""
        where = f"{self.title} > {self.heading}" if self.heading else self.title
        return ContextItem(
            source=CONTEXT_SOURCE,
            ref=f"document:{self.document_id}#{self.position}",
            text=f"{where}\n{self.text}",
            trust=Trust.EXTERNAL,
            tenant_id=tenant_id,
            data_class=self.data_class,
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    lanes: tuple[str, ...]  # the lanes that ran
    degraded: str | None = None  # e.g. "vector lane off: ai_off"; shown to the caller, never hidden (02/B7)
