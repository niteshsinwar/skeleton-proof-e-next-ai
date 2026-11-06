# State homes

Every kind of state has exactly one home; the API tier is stateless (01/T1).

| State | Home | Notes |
|---|---|---|
| System of record | Postgres (`app` schema) | `OPEN` |
| Audit | Postgres (`audit` schema), append-only | |
| Workflow and agent checkpoints | own schema, never the record | |
| Sessions | `OPEN` | |
| Cache | disposable; never authoritative for a decision | |
| Files | object storage | |
| Search index (chunks, vectors) | Postgres (`rag` schema), with pgvector | derived from documents: deleted with them, rebuilt never edited; live state is never answered from it (02/D12) |
| Behaviour configuration | versioned data in `apps/api/config/` | |
