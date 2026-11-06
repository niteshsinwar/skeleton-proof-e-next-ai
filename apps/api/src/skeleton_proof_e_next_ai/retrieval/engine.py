"""Hybrid search (04/X4): a lexical lane and a vector lane, each already filtered by tenant and role, fused by RRF.

Implements the domain's `Retriever` port. The store is passed in with each call's transaction; the query is embedded
before that transaction opens, because it is a model call. When embeddings are off or fail, search still answers from
the lexical lane and says it is degraded (01/R5, 02/B7). No score threshold decides anything: a weak hit is still only
a candidate, and whether to answer is the step's decision (abstain per class, 04/X4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ..domain.ports import DocumentStore, Embedder
from ..domain.retrieval import Chunk, Embedded, EmbedTask, SearchResult, SearchScope
from .chunking import chunk
from .fusion import rrf

LANE_DEPTH = 50  # candidates each lane contributes before fusion


class HybridRetriever:
    def __init__(self, embedder: Embedder, *, max_chunk_chars: int = 1200, lane_depth: int = LANE_DEPTH) -> None:
        self._embedder = embedder
        self.max_chunk_chars, self.lane_depth = max_chunk_chars, lane_depth

    @property
    def space(self) -> str | None:
        return self._embedder.space

    def chunk(self, text: str) -> list[Chunk]:
        return chunk(text, max_chars=self.max_chunk_chars)

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> Embedded:
        return await self._embedder.embed(texts, task=task)

    async def search(
        self, store: DocumentStore, scope: SearchScope, query: str, query_vector: Embedded, limit: int
    ) -> SearchResult:
        lanes = {"lexical": await store.lexical(scope, query, self.lane_depth)}
        degraded = None
        if query_vector.vectors and query_vector.space is not None:
            lanes["vector"] = await store.nearest(scope, query_vector.vectors[0], query_vector.space, self.lane_depth)
        else:
            degraded = f"vector lane off: {query_vector.failure}"
        fused = rrf(lanes)[:limit]
        found = await store.hits(scope, [key for key, _, _ in fused])
        hits = tuple(replace(found[key], score=score, lanes=by) for key, score, by in fused if key in found)
        return SearchResult(hits, tuple(lanes), degraded)
