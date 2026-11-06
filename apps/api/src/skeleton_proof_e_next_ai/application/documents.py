"""Document use cases: add, search, remove (04/X4). The shape every retrieval feature follows:

1. `prepare` authorises and chunks, with no transaction open; the caller then embeds the chunks (a model call).
2. `add` stores the document, its chunks and their vectors in one transaction, with an audit event.
3. `search` takes a query already embedded outside the transaction and runs the filtered lanes inside it.

Retrieved text is data for a step to read, never an instruction (05/SG5): `SearchHit.as_context` marks it untrusted.
Documents the caller may not see are reported exactly like documents that don't exist (02/A7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..domain.ai import DataClass
from ..domain.errors import InvariantViolated, NotFound
from ..domain.ids import new_id
from ..domain.ports import AuditEvent, AuditPort, DocumentStore, Retriever
from ..domain.principals import ROLE_CAPABILITIES, Capability, Principal
from ..domain.retrieval import Chunk, Document, Embedded, SearchResult, SearchScope

ENTITY = "document"


@dataclass(frozen=True, slots=True)
class Ports:
    store: DocumentStore
    audit: AuditPort


@dataclass(frozen=True, slots=True)
class Prepared:
    document: Document
    chunks: tuple[Chunk, ...]


def scope(principal: Principal) -> SearchScope:
    return SearchScope(principal.tenant_id, principal.roles)


def prepare(
    retriever: Retriever,
    principal: Principal,
    *,
    title: str,
    text: str,
    source_ref: str,
    data_class: DataClass,
    allowed_roles: tuple[str, ...],
    now: datetime,
) -> Prepared:
    principal.require(Capability.DOCUMENTS_MANAGE)
    unknown = sorted(set(allowed_roles) - set(ROLE_CAPABILITIES))
    if unknown:
        raise InvariantViolated(f"Unknown roles: {', '.join(unknown)}. A document no role can open helps no one.")
    document = Document(
        id=new_id(),
        tenant_id=principal.tenant_id,
        title=title,
        source_ref=source_ref,
        data_class=data_class,
        allowed_roles=tuple(sorted(set(allowed_roles))),
        version=1,
        created_by=principal.subject,
        created_at=now,
    )
    parts = tuple(retriever.chunk(text))
    if not parts:
        raise InvariantViolated("A document has some text to search.")
    return Prepared(document, parts)


async def add(ports: Ports, principal: Principal, prepared: Prepared, embedded: Embedded) -> None:
    principal.require(Capability.DOCUMENTS_MANAGE)
    await ports.store.add(prepared.document, prepared.chunks, embedded)
    vectors = f"embedded in {embedded.space}" if embedded.vectors is not None else f"not embedded ({embedded.failure})"
    await _audit(ports, principal, "document.added", prepared.document.id, f"{len(prepared.chunks)} chunks, {vectors}")


async def search(
    ports: Ports, retriever: Retriever, principal: Principal, query: str, query_vector: Embedded, limit: int
) -> SearchResult:
    principal.require(Capability.DOCUMENTS_READ)
    if not query.strip():
        raise InvariantViolated("Say what to search for.")
    return await retriever.search(ports.store, scope(principal), query, query_vector, limit)


async def remove(ports: Ports, principal: Principal, document_id: UUID) -> None:
    """Erasure (02/D8): the document and every chunk and vector made from it go together."""
    principal.require(Capability.DOCUMENTS_MANAGE)
    if await ports.store.get(document_id, scope(principal)) is None:
        raise NotFound("No such document.")
    await ports.store.delete(document_id)
    await _audit(ports, principal, "document.removed", document_id, None)


async def _audit(ports: Ports, principal: Principal, action: str, document_id: UUID, reason: str | None) -> None:
    await ports.audit.append(
        AuditEvent(
            action=action,
            entity=ENTITY,
            entity_id=str(document_id),
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=None,
            after_version=None,
            reason=reason,
        )
    )
