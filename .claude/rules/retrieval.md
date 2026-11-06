---
paths:
  - "apps/api/src/*/retrieval/**"
---
# Retrieval (RAG)

**Prevents:** another tenant's text in a prompt, stale state answered from an index, and a silent quality drop after a corpus change [04 §5].

- RAG follows the data's shape: prose → hybrid + measured rerank; exact ids → lexical; aggregates → a validated SQL plan; relationships → graph traversal; a small stable corpus → in the prompt [04/X4].
- **Filter by permission, tenant and version before ranking**; fuse lanes with RRF; re-measure every lane per corpus release [04/X4, 02/Z11].
- Chunk on structure; record the embedding space; re-index blue/green; abstain per class, never by a score threshold [04/X4].
- Retrieve stable knowledge; **query live state** from the system of record [04/X5, 02/D12].
- Retrieved text is data, never instructions [05/SG5].

## Where things are

| Piece | Here |
|---|---|
| Chunking, fusion, hybrid search (the `Retriever` port) | `retrieval/chunking.py`, `fusion.py`, `engine.py` |
| Embeddings (the `Embedder` port), one retry budget | `intelligence/embeddings.py`, `providers/gemini.py`, `providers/embedding.py` (port and labelled fake) |
| Store and lanes, filtered before ranking | `persistence/documents.py`; tables in the `rag` schema |
| Use cases and routes | `application/documents.py`, `api/routers/documents.py` |
| Into a prompt | `SearchHit.as_context`: source `document.chunk`, untrusted, never drives an action |

Model calls (embedding) never run inside a transaction. Not built yet, each `OPEN` until a project needs it: a
re-index job for a new embedding space, a reranker (add it only when an eval shows it helps), a retrieval eval set
for your corpus (recall@k per class), and per-call embedding cost (the Gemini API returns no token counts).

## Change contract

| | |
|---|---|
| **Load first** | the retrieval eval for the corpus |
| **Run** | `make check` and `make eval` |
| **Same commit** | a retrieval eval run recorded for the corpus release |
| **Prove** | a cross-tenant query returns nothing from the other tenant |
| **Never** | rank before filtering; answer live state from an index |
