"""The document store (implements `DocumentStore`): documents, chunks, and the two search lanes (04/X4).

Every lane filters by tenant and role in the same statement that ranks, so nothing the caller may not see is ever a
candidate (02/Z11). Row-level security holds the tenant line too in multi-tenant projects; the explicit filter keeps
single-tenant projects and the query plans honest. Vectors are compared only within one embedding space.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, insert, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.ai import DataClass
from ..domain.retrieval import Chunk, ChunkKey, Document, Embedded, SearchHit, SearchScope
from .schema import chunks, documents


def _visible(scope: SearchScope) -> ColumnElement[bool]:
    return (chunks.c.tenant_id == scope.tenant_id) & or_(
        func.cardinality(chunks.c.allowed_roles) == 0, chunks.c.allowed_roles.overlap(sorted(scope.roles))
    )


class PgDocuments:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def add(self, document: Document, parts: Sequence[Chunk], embedded: Embedded) -> None:
        vectors = embedded.vectors
        if vectors is not None and len(vectors) != len(parts):
            raise ValueError("one vector per chunk, or none at all")
        await self.conn.execute(
            insert(documents).values(
                id=document.id,
                tenant_id=document.tenant_id,
                title=document.title,
                source_ref=document.source_ref,
                data_class=document.data_class.value,
                allowed_roles=list(document.allowed_roles),
                version=document.version,
                created_by=document.created_by,
                created_at=document.created_at,
                updated_at=document.created_at,
            )
        )
        if not parts:
            return
        await self.conn.execute(
            insert(chunks),
            [
                {
                    "document_id": document.id,
                    "position": part.position,
                    "tenant_id": document.tenant_id,
                    "allowed_roles": list(document.allowed_roles),
                    "heading": part.heading,
                    "text": part.text,
                    "embedding": list(vectors[i]) if vectors is not None else None,
                    "embedding_space": embedded.space if vectors is not None else None,
                }
                for i, part in enumerate(parts)
            ],
        )

    async def get(self, document_id: UUID, scope: SearchScope) -> Document | None:
        row = (
            await self.conn.execute(
                select(documents).where(documents.c.id == document_id, documents.c.tenant_id == scope.tenant_id)
            )
        ).one_or_none()
        if row is None:
            return None
        document = Document(
            id=row.id,
            tenant_id=row.tenant_id,
            title=row.title,
            source_ref=row.source_ref,
            data_class=DataClass(row.data_class),
            allowed_roles=tuple(row.allowed_roles),
            version=row.version,
            created_by=row.created_by,
            created_at=row.created_at,
        )
        return document if document.visible_to(scope.roles) else None

    async def delete(self, document_id: UUID) -> None:
        await self.conn.execute(delete(documents).where(documents.c.id == document_id))  # chunks cascade

    async def lexical(self, scope: SearchScope, query: str, limit: int) -> list[ChunkKey]:
        tsquery = func.websearch_to_tsquery("simple", query)
        rows = await self.conn.execute(
            select(chunks.c.document_id, chunks.c.position)
            .where(_visible(scope), chunks.c.search.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(chunks.c.search, tsquery).desc(), chunks.c.document_id, chunks.c.position)
            .limit(limit)
        )
        return [(r.document_id, r.position) for r in rows]

    async def nearest(self, scope: SearchScope, vector: Sequence[float], space: str, limit: int) -> list[ChunkKey]:
        # Filtered HNSW scans keep going until `limit` rows pass the filter, in exact distance order (pgvector 0.8).
        await self.conn.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        rows = await self.conn.execute(
            select(chunks.c.document_id, chunks.c.position)
            .where(_visible(scope), chunks.c.embedding_space == space)
            .order_by(chunks.c.embedding.cosine_distance(list(vector)))
            .limit(limit)
        )
        return [(r.document_id, r.position) for r in rows]

    async def hits(self, scope: SearchScope, keys: Sequence[ChunkKey]) -> Mapping[ChunkKey, SearchHit]:
        if not keys:
            return {}
        rows = await self.conn.execute(
            select(chunks.c.document_id, chunks.c.position, chunks.c.heading, chunks.c.text, documents.c.title)
            .add_columns(documents.c.data_class)
            .join(documents, documents.c.id == chunks.c.document_id)
            .where(_visible(scope), tuple_(chunks.c.document_id, chunks.c.position).in_(list(keys)))
        )
        return {
            (r.document_id, r.position): SearchHit(
                document_id=r.document_id,
                position=r.position,
                title=r.title,
                heading=r.heading,
                text=r.text,
                data_class=DataClass(r.data_class),
                score=0.0,
                lanes=(),
            )
            for r in rows
        }
