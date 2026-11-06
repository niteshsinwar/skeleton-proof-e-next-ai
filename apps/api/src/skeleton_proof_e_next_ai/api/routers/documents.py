"""Document routes: add, search, remove (04/X4). Model calls (embedding) never run inside a transaction (plans/b4)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from ...application import documents as uc
from ...domain.ai import DataClass
from ...domain.ports import StoredResponse
from ...domain.principals import Capability
from ...domain.retrieval import EmbedTask
from ...persistence.documents import PgDocuments
from ...persistence.records import PgAudit, PgIdempotency
from ..deps import CurrentPrincipal, IdempotencyKey, now, rate_limited, request_hash, state
from ..schemas.documents import AddDocument, DocumentOut, HitOut, SearchDocuments, SearchOut

router = APIRouter(prefix="/documents", tags=["documents"])


def _ports(conn: AsyncConnection) -> uc.Ports:
    return uc.Ports(store=PgDocuments(conn), audit=PgAudit(conn))


@router.post("", status_code=201, response_model=DocumentOut, dependencies=[rate_limited("write")])
async def add_document(
    body: AddDocument, request: Request, principal: CurrentPrincipal, key: IdempotencyKey
) -> JSONResponse:
    st = state(request)
    scope, digest = f"{principal.subject}:add_document", request_hash(body.model_dump())
    prepared = uc.prepare(
        st.retriever,
        principal,
        title=body.title,
        text=body.text,
        source_ref=body.source_ref,
        data_class=DataClass(body.data_class),
        allowed_roles=tuple(body.allowed_roles),
        now=now(),
    )
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        # A replay answers before paying for embeddings again.
        if (stored := await PgIdempotency(conn, principal.tenant_id).lookup(scope, key, digest)) is not None:
            return JSONResponse(dict(stored.body), status_code=stored.status)
    embedded = await st.retriever.embed([c.text for c in prepared.chunks], task=EmbedTask.DOCUMENT)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        if (stored := await idem.lookup(scope, key, digest)) is not None:
            return JSONResponse(dict(stored.body), status_code=stored.status)
        await uc.add(_ports(conn), principal, prepared, embedded)
        out = DocumentOut(id=prepared.document.id, chunks=len(prepared.chunks), embedding_space=embedded.space)
        stored = StoredResponse(201, out.model_dump(mode="json"))
        await idem.remember(scope, key, digest, stored)
    return JSONResponse(dict(stored.body), status_code=201)


@router.post("/search", response_model=SearchOut, dependencies=[rate_limited("read")])
async def search_documents(body: SearchDocuments, request: Request, principal: CurrentPrincipal) -> SearchOut:
    st = state(request)
    principal.require(Capability.DOCUMENTS_READ)  # before the paid call, not only after it
    vector = await st.retriever.embed([body.query], task=EmbedTask.QUERY)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        result = await uc.search(_ports(conn), st.retriever, principal, body.query, vector, body.limit)
    return SearchOut(
        hits=[
            HitOut(
                document_id=h.document_id,
                position=h.position,
                title=h.title,
                heading=h.heading,
                text=h.text,
                score=h.score,
                lanes=list(h.lanes),
            )
            for h in result.hits
        ],
        lanes=list(result.lanes),
        degraded=result.degraded,
    )


@router.delete("/{document_id}", status_code=204, dependencies=[rate_limited("write")])
async def remove_document(document_id: UUID, request: Request, principal: CurrentPrincipal) -> Response:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        await uc.remove(_ports(conn), principal, document_id)
    return Response(status_code=204)
