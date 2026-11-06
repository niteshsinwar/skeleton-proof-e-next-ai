"""Tables (SQLAlchemy Core; the ORM loading path is never used, 02/BL2). One schema per owner (02/D7).

The migration in migrations/versions/ creates these; a drift test compares the two.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR

EMBEDDING_DIMENSIONS = 768  # ai/models.yaml `embeddings.default.dimensions`; a test holds them equal

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "pk": "pk_%(table_name)s",
    }
)

TS = DateTime(timezone=True)


# EXAMPLE SLICE
work_items = Table(
    "work_items",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("title", String(200), nullable=False),
    Column("state", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("submitted_by", Text),
    Column("decided_by", Text),
    Column("decision_reason", Text),
    Column("created_by_name", Text),
    Column("decided_by_name", Text),
    CheckConstraint("state in ('draft','submitted','approved','rejected')", name="state"),
    CheckConstraint("version >= 1", name="version"),
    Index("ix_work_items_tenant_created_by", "tenant_id", "created_by", "id"),
    schema="app",
)


idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("scope", Text, primary_key=True),
    Column("key", Text, primary_key=True),
    Column("request_hash", String(64), nullable=False),
    Column("status", Integer, nullable=False),
    Column("body", JSONB, nullable=False),
    Column("created_at", TS, nullable=False),
    schema="app",
)


outbox = Table(
    "outbox",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("aggregate", Text, nullable=False),
    Column("aggregate_id", Uuid, nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("published_at", TS),
    UniqueConstraint("aggregate", "aggregate_id", "sequence", name="uq_outbox_aggregate_sequence"),
    schema="app",
)


flags = Table(
    "flags",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("key", Text, primary_key=True),
    Column("enabled", Boolean, nullable=False),
    Column("updated_by", Text, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("reason", Text, nullable=False),
    schema="app",
)


uploads = Table(
    "uploads",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("stored_name", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    schema="app",
)


rate_limits = Table(
    "rate_limits",
    metadata,
    Column("key", Text, primary_key=True),
    Column("tat", TS, nullable=False),
    schema="app",
)


webhook_receipts = Table(
    "webhook_receipts",
    metadata,
    Column("webhook_id", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("received_at", TS, nullable=False),
    schema="app",
)


role_grants = Table(
    "role_grants",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("subject", Text, primary_key=True),
    Column("role", Text, primary_key=True),
    Column("granted_by", Text, nullable=False),
    Column("granted_at", TS, nullable=False),
    Column("revoked_by", Text),
    Column("revoked_at", TS),
    schema="app",
)


pending_changes = Table(
    "pending_changes",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("proposed_at", TS, nullable=False),
    Column("status", String(16), nullable=False),
    Column("decided_by", Text),
    Column("decided_at", TS),
    CheckConstraint("status in ('pending','approved','rejected')", name="status"),
    schema="app",
)


revoked_tokens = Table(
    "revoked_tokens",
    metadata,
    Column("token_sha256", String(64), primary_key=True),
    Column("expires_at", TS, nullable=False),
    Column("revoked_at", TS, nullable=False),
    schema="app",
)


audit_events = Table(
    "events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("at", TS, nullable=False),
    Column("tenant_id", Uuid, nullable=False),
    Column("action", Text, nullable=False),
    Column("entity", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("principal_kind", Text, nullable=False),
    Column("on_behalf_of", Text),
    Column("before_version", Integer),
    Column("after_version", Integer),
    Column("reason", Text),
    Column("correlation_id", Text, nullable=False),
    Column("sequence", BigInteger, nullable=False),
    Column("prev_hash", String(64)),
    Column("hash", String(64), nullable=False),
    UniqueConstraint("tenant_id", "sequence", name="uq_events_tenant_id"),
    CheckConstraint("(sequence = 1) = (prev_hash IS NULL)", name="chain_start"),
    schema="audit",
)


chain_heads = Table(
    "chain_heads",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("sequence", BigInteger, nullable=False),
    Column("hash", String(64)),
    schema="audit",
)


jobs = Table(
    "jobs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("run_after", TS, nullable=False),
    Column("locked_until", TS),
    Column("locked_by", Text),
    Column("last_error", Text),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    CheckConstraint("status in ('queued','running','awaiting_review','done','dead')", name="status"),
    Index("ix_jobs_status_run_after", "status", "run_after"),
    schema="jobs",
)


# The product AI's records (04/X6): append only; the migration grants insert and select, nothing more.
ai_attempts = Table(
    "attempts",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("step", Text, nullable=False),
    Column("agent", Text, nullable=False),
    Column("agent_version", Integer, nullable=False),
    Column("agent_hash", String(64), nullable=False),
    Column("route", Text, nullable=False),
    Column("mode", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("reason", Text),
    Column("abstention", Text),
    Column("provider", Text),
    Column("requested_model", Text),
    Column("served_model", Text),
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS, nullable=False),
    Column("entity", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("principal_kind", Text, nullable=False),
    Column("on_behalf_of", Text),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("cache_read_tokens", Integer),
    Column("cache_write_tokens", Integer),
    Column("cost_usd", Numeric(12, 6)),
    Column("price_snapshot", Text),
    Column("signals", JSONB, nullable=False),
    Column("correlation_id", Text, nullable=False),
    CheckConstraint("mode in ('live','fixture','ai_off')", name="mode"),
    CheckConstraint("status in ('succeeded','abstained','invalid','refused','failed')", name="status"),
    CheckConstraint("(status = 'abstained') = (abstention IS NOT NULL)", name="abstention"),
    CheckConstraint("status = 'succeeded' OR reason IS NOT NULL", name="reason"),
    CheckConstraint("mode = 'live' OR cost_usd IS NULL OR cost_usd = 0", name="spend"),
    CheckConstraint("finished_at >= started_at", name="finished"),
    Index("ix_attempts_tenant_started", "tenant_id", "started_at"),
    Index("ix_attempts_entity", "entity", "entity_id"),
    schema="ai",
)

ai_attempt_context = Table(
    "attempt_context",
    metadata,
    Column("attempt_id", Uuid, nullable=False),
    Column("position", Integer, nullable=False),
    Column("tenant_id", Uuid, nullable=False),
    Column("context_id", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("trust", Text, nullable=False),
    Column("data_class", Text, nullable=False),
    Column("included", Boolean, nullable=False),
    Column("drop_reason", Text),
    Column("token_estimate", Integer, nullable=False),
    Column("signals", JSONB, nullable=False),
    Column("text", Text, nullable=False),
    PrimaryKeyConstraint("attempt_id", "position", name="pk_attempt_context"),
    ForeignKeyConstraint(["attempt_id"], ["ai.attempts.id"], name="fk_attempt_context_attempt_id", ondelete="RESTRICT"),
    CheckConstraint("included = (drop_reason IS NULL)", name="drop"),
    schema="ai",
)

ai_attempt_requests = Table(
    "attempt_requests",
    metadata,
    Column("attempt_id", Uuid, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("tenant_id", Uuid, nullable=False),
    Column("kind", Text, nullable=False),
    Column("body", JSONB, nullable=False),
    PrimaryKeyConstraint("attempt_id", "seq", name="pk_attempt_requests"),
    ForeignKeyConstraint(
        ["attempt_id"], ["ai.attempts.id"], name="fk_attempt_requests_attempt_id", ondelete="RESTRICT"
    ),
    CheckConstraint("kind in ('model_call','tool_call','retrieval')", name="kind"),
    schema="ai",
)

ai_attempt_outputs = Table(
    "attempt_outputs",
    metadata,
    Column("attempt_id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("raw_text", Text),
    Column("byte_length", Integer),
    Column("result", JSONB),
    ForeignKeyConstraint(["attempt_id"], ["ai.attempts.id"], name="fk_attempt_outputs_attempt_id", ondelete="RESTRICT"),
    CheckConstraint("(raw_text IS NULL AND byte_length IS NULL) OR byte_length = octet_length(raw_text)", name="bytes"),
    schema="ai",
)

ai_feedback = Table(
    "feedback",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("attempt_id", Uuid, nullable=False),
    Column("tenant_id", Uuid, nullable=False),
    Column("given_by", Text, nullable=False),
    Column("verdict", String(16), nullable=False),
    Column("correction", Text),
    Column("created_at", TS, nullable=False),
    ForeignKeyConstraint(["attempt_id"], ["ai.attempts.id"], name="fk_feedback_attempt_id", ondelete="RESTRICT"),
    CheckConstraint("verdict in ('helpful','wrong','unsafe')", name="verdict"),
    Index("ix_feedback_attempt", "attempt_id"),
    schema="ai",
)

eval_runs = Table(
    "runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS, nullable=False),
    Column("mode", String(16), nullable=False),
    Column("dataset", Text, nullable=False),
    Column("dataset_version", Integer, nullable=False),
    Column("dataset_sha256", String(64), nullable=False),
    Column("step", Text, nullable=False),
    Column("agent_hash", String(64), nullable=False),
    Column("route", Text, nullable=False),
    Column("model", Text),
    Column("repetitions", Integer, nullable=False),
    Column("git_sha", Text, nullable=False),
    Column("cases", Integer, nullable=False),
    Column("passed", Integer, nullable=False),
    Column("failed", Integer, nullable=False),
    Column("degraded", Boolean, nullable=False),
    Column("by_layer", JSONB, nullable=False),
    CheckConstraint("mode = 'live'", name="live"),
    CheckConstraint("repetitions >= 3", name="repetitions"),
    schema="eval",
)

eval_results = Table(
    "results",
    metadata,
    Column("run_id", Uuid, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("repetition", Integer, nullable=False),
    Column("layer", Text, nullable=False),
    Column("tags", JSONB, nullable=False),
    Column("passed", Boolean, nullable=False),
    Column("grades", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    Column("cost_usd", Numeric(12, 6)),
    Column("output_sha256", String(64), nullable=False),
    Column("served_model", Text),
    PrimaryKeyConstraint("run_id", "case_id", "repetition", name="pk_results"),
    ForeignKeyConstraint(["run_id"], ["eval.runs.id"], name="fk_results_run_id", ondelete="RESTRICT"),
    schema="eval",
)

proposals = Table(
    "proposals",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("summary", Text, nullable=False),
    Column("evidence", JSONB, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("on_behalf_of", Text),
    Column("status", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("decided_by", Text),
    Column("decided_at", TS),
    Column("decision_reason", Text),
    Column("executed_at", TS),
    Column("outcome", JSONB),
    CheckConstraint("status in ('proposed','approved','rejected','executed','failed')", name="status"),
    CheckConstraint("version >= 1", name="version"),
    CheckConstraint("(status = 'proposed') = (decided_by IS NULL)", name="decided"),
    CheckConstraint("status <> 'rejected' OR decision_reason IS NOT NULL", name="rejection"),
    Index("ix_proposals_tenant_status", "tenant_id", "status", "created_at"),
    schema="app",
)


# Retrieval (04/X4). Who may see a chunk is copied onto it from its document, so the lanes filter by tenant and role
# in the same index scan that ranks, never afterwards. `search` is generated by the database from the chunk's text.
documents = Table(
    "documents",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, nullable=False),
    Column("title", String(300), nullable=False),
    Column("source_ref", Text, nullable=False),
    Column("data_class", String(16), nullable=False),
    Column("allowed_roles", ARRAY(Text), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    CheckConstraint("data_class in ('public','internal','confidential')", name="data_class"),
    CheckConstraint("version >= 1", name="version"),
    Index("ix_documents_tenant_created", "tenant_id", "created_at"),
    schema="rag",
)

chunks = Table(
    "chunks",
    metadata,
    Column("document_id", Uuid, nullable=False),
    Column("position", Integer, nullable=False),
    Column("tenant_id", Uuid, nullable=False),
    Column("allowed_roles", ARRAY(Text), nullable=False),
    Column("heading", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("search", TSVECTOR, Computed("to_tsvector('simple', heading || ' ' || text)", persisted=True)),
    Column("embedding", Vector(EMBEDDING_DIMENSIONS)),
    Column("embedding_space", Text),
    PrimaryKeyConstraint("document_id", "position", name="pk_chunks"),
    ForeignKeyConstraint(["document_id"], ["rag.documents.id"], name="fk_chunks_document_id", ondelete="CASCADE"),
    CheckConstraint("position >= 1", name="position"),
    CheckConstraint("(embedding IS NULL) = (embedding_space IS NULL)", name="embedding_space"),
    Index("ix_chunks_tenant_id", "tenant_id"),
    Index("ix_chunks_search", "search", postgresql_using="gin"),
    Index(
        "ix_chunks_embedding",
        "embedding",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    ),
    schema="rag",
)


# Each tenant's credentials for each outside MCP server (04/K3). The secret is sealed (security/sealed.py) with its
# tenant and server as context; access tokens are never stored.
mcp_connections = Table(
    "mcp_connections",
    metadata,
    Column("tenant_id", Uuid, nullable=False),
    Column("server", Text, nullable=False),
    Column("client_id", Text, nullable=False),
    Column("client_secret_sealed", Text, nullable=False),
    Column("connected_by", Text, nullable=False),
    Column("connected_at", TS, nullable=False),
    PrimaryKeyConstraint("tenant_id", "server", name="pk_mcp_connections"),
    schema="app",
)
