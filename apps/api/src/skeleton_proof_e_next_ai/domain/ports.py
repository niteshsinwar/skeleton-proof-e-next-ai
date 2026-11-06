"""Ports: shaped by what the domain and use cases need, one adapter per technology (02/B3).

Least privilege through the interface: the audit port can append and nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from .ai import Attempt, Proposal, StepInputs, StepResult, ToolResult
from .outside_tools import Connection, Credentials, Drift, OutsideTool
from .principals import Principal
from .retrieval import Chunk, ChunkKey, Document, Embedded, EmbedTask, SearchHit, SearchResult, SearchScope
from .work_items import WorkItem


@dataclass(frozen=True, slots=True)
class Page:
    items: list[WorkItem]
    next_cursor: str | None


class WorkItemRepository(Protocol):
    async def add(self, item: WorkItem) -> None: ...
    async def get(self, item_id: UUID) -> WorkItem | None: ...
    async def save(self, item: WorkItem, expected_version: int) -> bool: ...
    async def list(self, *, created_by: str | None, after: UUID | None, limit: int) -> list[WorkItem]: ...


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: str
    entity: str
    entity_id: str
    actor: str
    principal_kind: str
    on_behalf_of: str | None
    tenant_id: UUID
    before_version: int | None
    after_version: int | None
    reason: str | None = None


class GrantsPort(Protocol):
    """Who holds which role (02/Z5): read on every call, so a revoked role stops working at once (02/Z4)."""

    async def roles(self, tenant_id: UUID, subject: str) -> frozenset[str]: ...
    async def grant(self, tenant_id: UUID, subject: str, role: str, by: str) -> bool: ...
    async def revoke(self, tenant_id: UUID, subject: str, role: str, by: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PendingChange:
    id: UUID
    kind: str
    payload: Mapping[str, Any]
    reason: str
    proposed_by: str
    status: str


class ChangesPort(Protocol):
    """Dual authorisation (02/Z6): proposed changes wait for a second person; decided ones are never re-decided."""

    async def propose(self, tenant_id: UUID, kind: str, payload: Mapping[str, Any], reason: str, by: str) -> UUID: ...
    async def get(self, tenant_id: UUID, change_id: UUID) -> PendingChange | None: ...
    async def decide(self, tenant_id: UUID, change_id: UUID, approved: bool, by: str) -> bool: ...


class RevocationList(Protocol):
    """Sessions ended before their tokens expire (02/Z4). Append only, like the audit trail: nothing un-revokes."""

    async def revoke(self, token_sha256: str, expires_at: datetime) -> None: ...
    async def is_revoked(self, token_sha256: str, now: datetime) -> bool: ...


class AuditPort(Protocol):
    """Append only: there is deliberately no update or delete (02/B3, 02/D6)."""

    async def append(self, event: AuditEvent) -> None: ...


class OutboxPort(Protocol):
    async def publish(
        self, aggregate: str, aggregate_id: UUID, sequence: int, kind: str, payload: Mapping[str, Any]
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status: int
    body: Mapping[str, Any]


class IdempotencyPort(Protocol):
    async def lookup(self, scope: str, key: str, request_hash: str) -> StoredResponse | None: ...
    async def remember(self, scope: str, key: str, request_hash: str, response: StoredResponse) -> None: ...


class FlagPort(Protocol):
    async def enabled(self, key: str, tenant_id: UUID) -> bool: ...
    async def set(self, key: str, tenant_id: UUID, enabled: bool, actor: str, reason: str) -> None: ...


class AIRunner(Protocol):
    """Runs one registered AI step (04). Implemented in intelligence/, which the application never imports (02/B1)."""

    def steps(self) -> list[str]: ...

    def available(self, step: str) -> bool: ...

    async def run(self, step: str, inputs: StepInputs, principal: Principal) -> StepResult: ...


class AttemptLog(Protocol):
    """Every attempt's records (04/X6). Append only, like the audit trail: no update, no delete (02/B3)."""

    async def record(self, attempt: Attempt) -> None:
        """Serialises with other attempts of the same step on the same subject until the transaction ends (02/J6)."""
        ...

    async def superseded(self, attempt: Attempt) -> bool:
        """A run of the same step on the same subject that started later has already been recorded (02/J6)."""
        ...

    async def feedback(
        self, attempt_id: UUID, tenant_id: UUID, by: str, verdict: str, correction: str | None
    ) -> bool: ...

    async def spent_since(self, tenant_id: UUID, since: datetime) -> Decimal: ...


class ProposalStore(Protocol):
    """Proposals move through their lifecycle by version (02/A4); none is ever deleted."""

    async def add(self, proposal: Proposal) -> None: ...
    async def get(self, proposal_id: UUID) -> Proposal | None: ...
    async def save(self, proposal: Proposal, expected_version: int) -> bool: ...
    async def list_open(self, *, limit: int) -> list[Proposal]: ...


class ProposalExecutor(Protocol):
    """One per proposal kind, registered by the project. `precheck` re-validates live state just before it runs
    (04/G6): a reason string refuses; None lets `execute` run, which happens at most once per proposal."""

    async def precheck(self, proposal: Proposal, principal: Principal) -> str | None: ...
    async def execute(self, proposal: Proposal, principal: Principal) -> Mapping[str, Any]: ...


class ToolHandler(Protocol):
    """Runs the project's tools for an agent (04/K1–K2). Read tools return data; propose tools create a proposal and
    never act. Implemented by the application, so the caller's per-object authorisation applies (02/Z7)."""

    async def call(self, name: str, arguments: Mapping[str, Any], principal: Principal) -> ToolResult: ...


class ApprovalWorkflow(Protocol):
    """Waits for a person and then runs an approved proposal, once (04/G6–G7). Plain and LangGraph versions exist."""

    async def start(self, proposal_id: UUID) -> None: ...
    async def resume(self, proposal_id: UUID, *, approved: bool, decided_by: str, tenant_id: UUID) -> None: ...


class OutsideTools(Protocol):
    """Tools on outside MCP servers, as reviewed (intelligence/mcp.py). Every call re-checks the reviewed contract."""

    def servers(self) -> Sequence[str]: ...
    def tools(self) -> Sequence[OutsideTool]: ...
    def tool(self, key: str) -> OutsideTool | None: ...
    async def review(self, server: str, credentials: Credentials | None, tenant_id: UUID) -> list[Drift]: ...
    async def call(
        self, tool: OutsideTool, arguments: Mapping[str, Any], credentials: Credentials | None, tenant_id: UUID
    ) -> ToolResult: ...


class McpConnections(Protocol):
    """Each tenant's credentials for each outside server, sealed at rest."""

    async def put(self, tenant_id: UUID, server: str, credentials: Credentials, by: str, at: datetime) -> None: ...
    async def credentials(self, tenant_id: UUID, server: str) -> Credentials | None: ...
    async def list(self, tenant_id: UUID) -> list[Connection]: ...
    async def delete(self, tenant_id: UUID, server: str) -> bool: ...


class Embedder(Protocol):
    """Text to vectors in one embedding space. A model call, so it never runs inside a transaction (plans/b4)."""

    @property
    def space(self) -> str | None: ...  # None while embeddings are off

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> Embedded: ...


class DocumentStore(Protocol):
    """Documents and their chunks. Every read takes the scope and filters by it before ranking (04/X4, 02/Z11)."""

    async def add(self, document: Document, chunks: Sequence[Chunk], embedded: Embedded) -> None: ...
    async def get(self, document_id: UUID, scope: SearchScope) -> Document | None: ...
    async def delete(self, document_id: UUID) -> None: ...
    async def lexical(self, scope: SearchScope, query: str, limit: int) -> list[ChunkKey]: ...
    async def nearest(self, scope: SearchScope, vector: Sequence[float], space: str, limit: int) -> list[ChunkKey]: ...
    async def hits(self, scope: SearchScope, keys: Sequence[ChunkKey]) -> Mapping[ChunkKey, SearchHit]: ...


class Retriever(Protocol):
    """Chunking, embedding and hybrid search over a store (retrieval/). The store comes with each call's transaction."""

    def chunk(self, text: str) -> list[Chunk]: ...
    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> Embedded: ...
    async def search(
        self, store: DocumentStore, scope: SearchScope, query: str, query_vector: Embedded, limit: int
    ) -> SearchResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class BlobStore(Protocol):
    async def put(self, name: str, data: bytes) -> None: ...


class UploadLog(Protocol):
    async def add(
        self,
        upload_id: UUID,
        tenant_id: UUID,
        stored_name: str,
        media_type: str,
        size_bytes: int,
        created_by: str,
        created_at: datetime,
    ) -> None: ...
