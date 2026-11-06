# Gemini embeddings and pgvector (verified 2026-11-05)

What retrieval relies on. Re-verify within 21 days of relying on it again (10/H17, H20).

| Fact | Status | Source |
|---|---|---|
| `google-genai` 2.33.0 and `pgvector` 0.5.1 are the newest releases older than the 7-day cooldown (cutoff 2026-10-28) | READ | resolved with `uv lock` under `exclude-newer` |
| `client.aio.models.embed_content(model=, contents=[...], config=EmbedContentConfig(task_type=, output_dimensionality=, http_options=))`; the answer is `embeddings[i].values`, in input order | READ | installed `google/genai/models.py`, `types.py` |
| `HttpOptions.timeout` is in milliseconds; `HttpRetryOptions(attempts=1)` switches the SDK's own retries off | READ | installed `google/genai/types.py`, `_api_client.py` (`retry_args`) |
| `auto_truncate` is refused for the Gemini API (the SDK raises); it works only on Vertex | READ | installed `google/genai/models.py` (`_EmbedContentConfig_to_mldev`) |
| Errors: `errors.APIError(code, response_json)`, `ClientError` for 4xx, `ServerError` for 5xx; transport failures surface as `httpx.TimeoutException` / `ConnectError` | READ | installed `google/genai/errors.py`, `_api_client.py` |
| The Gemini API response carries no token counts for embeddings (`metadata.billable_character_count` is Vertex-only) | READ | installed `types.EmbedContentResponse`, `EmbedContentMetadata` |
| `gemini-embedding-001`: text only, 2048 input tokens, 3072 dimensions by default; only 3072 comes back normalised, so smaller sizes are normalised by the adapter | RETRIEVED | Google's Gemini API embeddings guide |
| Price `$0.15` per million input tokens (standard tier) | RETRIEVED | Google's Gemini API pricing page; check it before relying on a cost |
| pgvector: HNSW and IVFFlat index the `vector` type up to 2000 dimensions; `<=>` is cosine distance with `vector_cosine_ops` | RETRIEVED | pgvector README |
| pgvector 0.8 iterative index scans: `SET LOCAL hnsw.iterative_scan = strict_order` keeps a filtered HNSW scan going until `LIMIT` rows pass, in exact order | RETRIEVED | pgvector README (the tests run on tables too small for the planner to choose the index) |
| `vector` is not a trusted extension: `CREATE EXTENSION` needs a superuser (or the managed database's equivalent role) | READ | `vector.control` (no `trusted = true`), pgvector 0.8.7 as installed |
| `pgvector.sqlalchemy.Vector(dim)` with `.cosine_distance(...)`; it binds a Python list, so numpy is not needed | READ | installed `pgvector/sqlalchemy/vector.py` |
