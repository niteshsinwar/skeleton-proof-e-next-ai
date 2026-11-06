"""Baseline: schemas per owner, grants as the control, row-level security (02/D7, 02/D6, 02/Z10).

Two roles, neither a table owner, neither with BYPASSRLS:
  app_user   the API. Audit is insert-only for it.
  app_worker the outbox relay and job worker. It reads the outbox across tenants through its own policy.
Roles are cluster-wide, so they are created only if missing and never dropped by a downgrade.

Revision: 0001 (down: none)
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN CREATE ROLE app_user NOLOGIN; END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN CREATE ROLE app_worker NOLOGIN; END IF;
        END $$
    """)
    op.execute("CREATE SCHEMA app")
    op.execute("CREATE SCHEMA audit")
    op.execute("CREATE SCHEMA jobs")

    # EXAMPLE SLICE
    op.execute("""
        CREATE TABLE app.work_items (
          id uuid NOT NULL CONSTRAINT pk_work_items PRIMARY KEY,
          tenant_id uuid NOT NULL,
          title varchar(200) NOT NULL,
          state varchar(16) NOT NULL CONSTRAINT ck_work_items_state
            CHECK (state in ('draft','submitted','approved','rejected')),
          version integer NOT NULL CONSTRAINT ck_work_items_version CHECK (version >= 1),
          created_by text NOT NULL,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          submitted_by text,
          decided_by text,
          decision_reason text,
          created_by_name text,
          decided_by_name text
        )""")
    op.execute("CREATE INDEX ix_work_items_tenant_created_by ON app.work_items (tenant_id, created_by, id)")

    op.execute("""
        CREATE TABLE app.idempotency_keys (
          tenant_id uuid NOT NULL, scope text NOT NULL, key text NOT NULL,
          request_hash varchar(64) NOT NULL, status integer NOT NULL, body jsonb NOT NULL,
          created_at timestamptz NOT NULL,
          CONSTRAINT pk_idempotency_keys PRIMARY KEY (tenant_id, scope, key)
        )""")
    op.execute("""
        CREATE TABLE app.outbox (
          id uuid NOT NULL CONSTRAINT pk_outbox PRIMARY KEY,
          tenant_id uuid NOT NULL, aggregate text NOT NULL, aggregate_id uuid NOT NULL,
          sequence integer NOT NULL, kind text NOT NULL, payload jsonb NOT NULL,
          created_at timestamptz NOT NULL, published_at timestamptz,
          CONSTRAINT uq_outbox_aggregate_sequence UNIQUE (aggregate, aggregate_id, sequence)
        )""")
    op.execute("""
        CREATE TABLE app.flags (
          tenant_id uuid NOT NULL, key text NOT NULL, enabled boolean NOT NULL,
          updated_by text NOT NULL, updated_at timestamptz NOT NULL, reason text NOT NULL,
          CONSTRAINT pk_flags PRIMARY KEY (tenant_id, key)
        )""")
    op.execute("""
        CREATE TABLE app.uploads (
          id uuid NOT NULL CONSTRAINT pk_uploads PRIMARY KEY,
          tenant_id uuid NOT NULL, stored_name text NOT NULL, media_type text NOT NULL,
          size_bytes bigint NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL
        )""")
    op.execute(
        "CREATE TABLE app.rate_limits (key text NOT NULL CONSTRAINT pk_rate_limits PRIMARY KEY, tat timestamptz NOT NULL)"
    )
    op.execute("""
        CREATE TABLE app.webhook_receipts (
          webhook_id text NOT NULL CONSTRAINT pk_webhook_receipts PRIMARY KEY,
          source text NOT NULL, received_at timestamptz NOT NULL
        )""")
    # Roles are held by the API, not read from tokens, so removing one takes effect on the next call (02/Z4, Z5).
    op.execute("""
        CREATE TABLE app.role_grants (
          tenant_id uuid NOT NULL, subject text NOT NULL, role text NOT NULL,
          granted_by text NOT NULL, granted_at timestamptz NOT NULL, revoked_by text, revoked_at timestamptz,
          CONSTRAINT pk_role_grants PRIMARY KEY (tenant_id, subject, role)
        )""")
    # Dual authorisation at tier E (02/Z6): a sensitive change waits here until a second person approves it.
    op.execute("""
        CREATE TABLE app.pending_changes (
          id uuid NOT NULL CONSTRAINT pk_pending_changes PRIMARY KEY,
          tenant_id uuid NOT NULL, kind text NOT NULL, payload jsonb NOT NULL, reason text NOT NULL,
          proposed_by text NOT NULL, proposed_at timestamptz NOT NULL,
          status varchar(16) NOT NULL CONSTRAINT ck_pending_changes_status CHECK (status in ('pending','approved','rejected')),
          decided_by text, decided_at timestamptz
        )""")
    op.execute("""
        CREATE TABLE app.revoked_tokens (
          token_sha256 varchar(64) NOT NULL CONSTRAINT pk_revoked_tokens PRIMARY KEY,
          expires_at timestamptz NOT NULL, revoked_at timestamptz NOT NULL
        )""")
    op.execute("""
        CREATE TABLE audit.events (
          id uuid NOT NULL CONSTRAINT pk_events PRIMARY KEY,
          at timestamptz NOT NULL, tenant_id uuid NOT NULL, action text NOT NULL, entity text NOT NULL,
          entity_id text NOT NULL, actor text NOT NULL, principal_kind text NOT NULL, on_behalf_of text,
          before_version integer, after_version integer, reason text, correlation_id text NOT NULL,
          sequence bigint NOT NULL, prev_hash varchar(64), hash varchar(64) NOT NULL,
          CONSTRAINT uq_events_tenant_id UNIQUE (tenant_id, sequence),
          CONSTRAINT ck_events_chain_start CHECK ((sequence = 1) = (prev_hash IS NULL))
        )""")
    # The tier-E hash chain (02/D6): one locked head per tenant, so writers can't fork the chain.
    op.execute("""
        CREATE TABLE audit.chain_heads (
          tenant_id uuid NOT NULL CONSTRAINT pk_chain_heads PRIMARY KEY,
          sequence bigint NOT NULL, hash varchar(64)
        )""")
    op.execute("GRANT SELECT, INSERT, UPDATE ON audit.chain_heads TO app_user")
    op.execute("""
        CREATE TABLE jobs.jobs (
          id uuid NOT NULL CONSTRAINT pk_jobs PRIMARY KEY,
          kind text NOT NULL, idempotency_key text NOT NULL CONSTRAINT uq_jobs_idempotency_key UNIQUE,
          payload jsonb NOT NULL,
          status varchar(16) NOT NULL CONSTRAINT ck_jobs_status
            CHECK (status in ('queued','running','awaiting_review','done','dead')),
          attempts integer NOT NULL, max_attempts integer NOT NULL, run_after timestamptz NOT NULL,
          locked_until timestamptz, locked_by text, last_error text,
          created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
        )""")
    op.execute("CREATE INDEX ix_jobs_status_run_after ON jobs.jobs (status, run_after)")

    # Grants are the control (02/D7). No DELETE anywhere; audit is append-only for both roles (02/D6).
    op.execute("GRANT USAGE ON SCHEMA app, audit, jobs TO app_user, app_worker")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.work_items, app.rate_limits TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.flags TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.role_grants TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.pending_changes TO app_user")
    op.execute("GRANT SELECT, INSERT ON app.idempotency_keys, app.revoked_tokens TO app_user")
    op.execute("GRANT SELECT, INSERT ON app.uploads TO app_user")
    op.execute("GRANT SELECT, INSERT ON app.outbox TO app_user")
    op.execute("GRANT SELECT, INSERT ON app.webhook_receipts TO app_user")
    op.execute("GRANT INSERT ON audit.events TO app_user, app_worker")
    op.execute("GRANT SELECT, UPDATE ON app.outbox TO app_worker")
    op.execute("GRANT SELECT, INSERT, UPDATE ON jobs.jobs TO app_user, app_worker")
    op.execute("GRANT SELECT ON alembic_version TO app_user")  # readiness compares it with the code's head
    # Row-level security done right (02/Z10): FORCE, USING + WITH CHECK, fail closed when the tenant is unset.
    for table in (
        "app.work_items",
        "app.idempotency_keys",
        "app.outbox",
        "app.flags",
        "app.uploads",
        "app.role_grants",
        "app.pending_changes",
        "audit.events",
        "audit.chain_heads",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} TO app_user USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("CREATE POLICY worker_relay ON app.outbox TO app_worker USING (true) WITH CHECK (true)")
    op.execute("CREATE POLICY worker_audit ON audit.events TO app_worker USING (false) WITH CHECK (true)")
    _ai_records()
    _eval_runs()
    _proposals()
    _agent_checkpoints()
    _retrieval()
    _mcp_connections()


def _ai_records() -> None:
    # The product AI's records (04/X6, plans/b4): what each attempt was shown, what it asked, what it said, and what it
    # cost. Append only, like audit: the app may insert and read, never update or delete (02/D6). The checks mirror
    # the domain's rules, so a bad record is refused by the database too.
    op.execute("CREATE SCHEMA ai")
    op.execute("""
        CREATE TABLE ai.attempts (
          id uuid NOT NULL CONSTRAINT pk_attempts PRIMARY KEY,
          tenant_id uuid NOT NULL, step text NOT NULL, agent text NOT NULL, agent_version integer NOT NULL,
          agent_hash varchar(64) NOT NULL, route text NOT NULL,
          mode varchar(16) NOT NULL CONSTRAINT ck_attempts_mode CHECK (mode in ('live','fixture','ai_off')),
          status varchar(16) NOT NULL
            CONSTRAINT ck_attempts_status CHECK (status in ('succeeded','abstained','invalid','refused','failed')),
          reason text, abstention text, provider text, requested_model text, served_model text,
          started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
          entity text NOT NULL, entity_id text NOT NULL, actor text NOT NULL, principal_kind text NOT NULL,
          on_behalf_of text,
          input_tokens integer, output_tokens integer, cache_read_tokens integer, cache_write_tokens integer,
          cost_usd numeric(12, 6), price_snapshot text,
          signals jsonb NOT NULL, correlation_id text NOT NULL,
          CONSTRAINT ck_attempts_abstention CHECK ((status = 'abstained') = (abstention IS NOT NULL)),
          CONSTRAINT ck_attempts_reason CHECK (status = 'succeeded' OR reason IS NOT NULL),
          CONSTRAINT ck_attempts_spend CHECK (mode = 'live' OR cost_usd IS NULL OR cost_usd = 0),
          CONSTRAINT ck_attempts_finished CHECK (finished_at >= started_at)
        )""")
    op.execute("CREATE INDEX ix_attempts_tenant_started ON ai.attempts (tenant_id, started_at)")
    op.execute("CREATE INDEX ix_attempts_entity ON ai.attempts (entity, entity_id)")
    op.execute("""
        CREATE TABLE ai.attempt_context (
          attempt_id uuid NOT NULL
            CONSTRAINT fk_attempt_context_attempt_id REFERENCES ai.attempts (id) ON DELETE RESTRICT,
          position integer NOT NULL, tenant_id uuid NOT NULL, context_id text NOT NULL, source text NOT NULL,
          ref text NOT NULL, trust text NOT NULL, data_class text NOT NULL, included boolean NOT NULL, drop_reason text,
          token_estimate integer NOT NULL, signals jsonb NOT NULL, text text NOT NULL,
          CONSTRAINT pk_attempt_context PRIMARY KEY (attempt_id, position),
          CONSTRAINT ck_attempt_context_drop CHECK (included = (drop_reason IS NULL))
        )""")
    op.execute("""
        CREATE TABLE ai.attempt_requests (
          attempt_id uuid NOT NULL
            CONSTRAINT fk_attempt_requests_attempt_id REFERENCES ai.attempts (id) ON DELETE RESTRICT,
          seq integer NOT NULL, tenant_id uuid NOT NULL,
          kind text NOT NULL CONSTRAINT ck_attempt_requests_kind CHECK (kind in ('model_call','tool_call','retrieval')),
          body jsonb NOT NULL,
          CONSTRAINT pk_attempt_requests PRIMARY KEY (attempt_id, seq)
        )""")
    op.execute("""
        CREATE TABLE ai.attempt_outputs (
          attempt_id uuid NOT NULL CONSTRAINT pk_attempt_outputs PRIMARY KEY
            CONSTRAINT fk_attempt_outputs_attempt_id REFERENCES ai.attempts (id) ON DELETE RESTRICT,
          tenant_id uuid NOT NULL, raw_text text, byte_length integer, result jsonb,
          CONSTRAINT ck_attempt_outputs_bytes
            CHECK ((raw_text IS NULL AND byte_length IS NULL) OR byte_length = octet_length(raw_text))
        )""")
    # Feedback on an attempt (06/E10): every correction is an eval candidate; exporting them is a query, not a project.
    op.execute("""
        CREATE TABLE ai.feedback (
          id uuid NOT NULL CONSTRAINT pk_feedback PRIMARY KEY,
          attempt_id uuid NOT NULL CONSTRAINT fk_feedback_attempt_id REFERENCES ai.attempts (id) ON DELETE RESTRICT,
          tenant_id uuid NOT NULL, given_by text NOT NULL,
          verdict varchar(16) NOT NULL CONSTRAINT ck_feedback_verdict CHECK (verdict in ('helpful','wrong','unsafe')),
          correction text, created_at timestamptz NOT NULL
        )""")
    op.execute("CREATE INDEX ix_feedback_attempt ON ai.feedback (attempt_id)")
    op.execute("GRANT USAGE ON SCHEMA ai TO app_user")
    op.execute(
        "GRANT SELECT, INSERT ON ai.attempts, ai.attempt_context, ai.attempt_requests, ai.attempt_outputs, ai.feedback "
        "TO app_user"
    )
    for table in ("ai.attempts", "ai.attempt_context", "ai.attempt_requests", "ai.attempt_outputs", "ai.feedback"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} TO app_user USING ({TENANT}) WITH CHECK ({TENANT})")


def _eval_runs() -> None:
    # Recorded eval runs (06/E7): live runs only, at least three repetitions, never updated (Aegis B13).
    op.execute("CREATE SCHEMA eval")
    op.execute("""
        CREATE TABLE eval.runs (
          id uuid NOT NULL CONSTRAINT pk_runs PRIMARY KEY,
          started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
          mode varchar(16) NOT NULL CONSTRAINT ck_runs_live CHECK (mode = 'live'),
          dataset text NOT NULL, dataset_version integer NOT NULL, dataset_sha256 varchar(64) NOT NULL,
          step text NOT NULL, agent_hash varchar(64) NOT NULL, route text NOT NULL, model text,
          repetitions integer NOT NULL CONSTRAINT ck_runs_repetitions CHECK (repetitions >= 3),
          git_sha text NOT NULL, cases integer NOT NULL, passed integer NOT NULL, failed integer NOT NULL,
          degraded boolean NOT NULL, by_layer jsonb NOT NULL
        )""")
    op.execute("""
        CREATE TABLE eval.results (
          run_id uuid NOT NULL CONSTRAINT fk_results_run_id REFERENCES eval.runs (id) ON DELETE RESTRICT,
          case_id text NOT NULL, repetition integer NOT NULL, layer text NOT NULL, tags jsonb NOT NULL,
          passed boolean NOT NULL, grades jsonb NOT NULL, status text NOT NULL, reason text,
          cost_usd numeric(12, 6), output_sha256 varchar(64) NOT NULL, served_model text,
          CONSTRAINT pk_results PRIMARY KEY (run_id, case_id, repetition)
        )""")
    op.execute("GRANT USAGE ON SCHEMA eval TO app_user")
    op.execute("GRANT SELECT, INSERT ON eval.runs, eval.results TO app_user")


def _proposals() -> None:
    # The governed write path (README #9, 04/G7): a proposal moves through its lifecycle by version; none is deleted.
    op.execute("""
        CREATE TABLE app.proposals (
          id uuid NOT NULL CONSTRAINT pk_proposals PRIMARY KEY,
          tenant_id uuid NOT NULL, kind text NOT NULL, payload jsonb NOT NULL, summary text NOT NULL,
          evidence jsonb NOT NULL, proposed_by text NOT NULL, on_behalf_of text,
          status varchar(16) NOT NULL
            CONSTRAINT ck_proposals_status CHECK (status in ('proposed','approved','rejected','executed','failed')),
          version integer NOT NULL CONSTRAINT ck_proposals_version CHECK (version >= 1),
          created_at timestamptz NOT NULL, decided_by text, decided_at timestamptz, decision_reason text,
          executed_at timestamptz, outcome jsonb,
          CONSTRAINT ck_proposals_decided CHECK ((status = 'proposed') = (decided_by IS NULL)),
          CONSTRAINT ck_proposals_rejection CHECK (status <> 'rejected' OR decision_reason IS NOT NULL)
        )""")
    op.execute("CREATE INDEX ix_proposals_tenant_status ON app.proposals (tenant_id, status, created_at)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.proposals TO app_user")
    op.execute("ALTER TABLE app.proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.proposals FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON app.proposals TO app_user USING ({TENANT}) WITH CHECK ({TENANT})")


def _agent_checkpoints() -> None:
    # LangGraph's checkpoints (13/SK5), in their own schema: never the record (01/T1). Copied from
    # langgraph-checkpoint-postgres 3.2.0's MIGRATIONS (indexes without CONCURRENTLY on fresh tables); an integration
    # test compares them with the library's own setup(), so an upgrade that changes them needs a new migration.
    op.execute("CREATE SCHEMA agent_checkpoints")
    op.execute("CREATE TABLE agent_checkpoints.checkpoint_migrations (v integer PRIMARY KEY)")
    op.execute("""
        CREATE TABLE agent_checkpoints.checkpoints (
          thread_id text NOT NULL, checkpoint_ns text NOT NULL DEFAULT '', checkpoint_id text NOT NULL,
          parent_checkpoint_id text, type text, checkpoint jsonb NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
          PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )""")
    op.execute("""
        CREATE TABLE agent_checkpoints.checkpoint_blobs (
          thread_id text NOT NULL, checkpoint_ns text NOT NULL DEFAULT '', channel text NOT NULL,
          version text NOT NULL, type text NOT NULL, blob bytea,
          PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        )""")
    op.execute("""
        CREATE TABLE agent_checkpoints.checkpoint_writes (
          thread_id text NOT NULL, checkpoint_ns text NOT NULL DEFAULT '', checkpoint_id text NOT NULL,
          task_id text NOT NULL, idx integer NOT NULL, channel text NOT NULL, type text, blob bytea NOT NULL,
          task_path text NOT NULL DEFAULT '',
          PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )""")
    op.execute("CREATE INDEX checkpoints_thread_id_idx ON agent_checkpoints.checkpoints (thread_id)")
    op.execute("CREATE INDEX checkpoint_blobs_thread_id_idx ON agent_checkpoints.checkpoint_blobs (thread_id)")
    op.execute("CREATE INDEX checkpoint_writes_thread_id_idx ON agent_checkpoints.checkpoint_writes (thread_id)")
    op.execute("INSERT INTO agent_checkpoints.checkpoint_migrations (v) SELECT generate_series(0, 9)")
    op.execute("GRANT USAGE ON SCHEMA agent_checkpoints TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA agent_checkpoints TO app_user")


def _retrieval() -> None:
    # Retrieval (04/X4, plans/b4). pgvector is not a trusted extension: creating it needs a superuser, or the managed
    # database's equivalent role. It is never dropped by a downgrade (other databases on the cluster may use it).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA rag")
    op.execute("""
        CREATE TABLE rag.documents (
          id uuid NOT NULL CONSTRAINT pk_documents PRIMARY KEY,
          tenant_id uuid NOT NULL, title varchar(300) NOT NULL, source_ref text NOT NULL,
          data_class varchar(16) NOT NULL
            CONSTRAINT ck_documents_data_class CHECK (data_class in ('public','internal','confidential')),
          allowed_roles text[] NOT NULL,
          version integer NOT NULL CONSTRAINT ck_documents_version CHECK (version >= 1),
          created_by text NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
        )""")
    op.execute("CREATE INDEX ix_documents_tenant_created ON rag.documents (tenant_id, created_at)")
    # A chunk's size matches ai/models.yaml `embeddings.default.dimensions`; another size is a new space, so a new
    # column and a re-index, never a mix (04/X4).
    op.execute("""
        CREATE TABLE rag.chunks (
          document_id uuid NOT NULL, position integer NOT NULL CONSTRAINT ck_chunks_position CHECK (position >= 1),
          tenant_id uuid NOT NULL, allowed_roles text[] NOT NULL, heading text NOT NULL, text text NOT NULL,
          search tsvector GENERATED ALWAYS AS (to_tsvector('simple', heading || ' ' || text)) STORED,
          embedding vector(768), embedding_space text,
          CONSTRAINT pk_chunks PRIMARY KEY (document_id, position),
          CONSTRAINT fk_chunks_document_id FOREIGN KEY (document_id) REFERENCES rag.documents (id) ON DELETE CASCADE,
          CONSTRAINT ck_chunks_embedding_space CHECK ((embedding IS NULL) = (embedding_space IS NULL))
        )""")
    op.execute("CREATE INDEX ix_chunks_tenant_id ON rag.chunks (tenant_id)")
    op.execute("CREATE INDEX ix_chunks_search ON rag.chunks USING gin (search)")
    op.execute("CREATE INDEX ix_chunks_embedding ON rag.chunks USING hnsw (embedding vector_cosine_ops)")
    op.execute("GRANT USAGE ON SCHEMA rag TO app_user")
    # Documents are replaced, not edited: insert, read and delete (erasure, 02/D8). No UPDATE is granted.
    op.execute("GRANT SELECT, INSERT, DELETE ON rag.documents, rag.chunks TO app_user")
    for table in ("rag.documents", "rag.chunks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} TO app_user USING ({TENANT}) WITH CHECK ({TENANT})")


def _mcp_connections() -> None:
    # Credentials for outside MCP servers, per tenant (04/K3). Sealed at rest; replaced or removed by an admin.
    op.execute("""
        CREATE TABLE app.mcp_connections (
          tenant_id uuid NOT NULL, server text NOT NULL, client_id text NOT NULL,
          client_secret_sealed text NOT NULL
            CONSTRAINT ck_mcp_connections_sealed CHECK (client_secret_sealed LIKE 'k%:%'),
          connected_by text NOT NULL, connected_at timestamptz NOT NULL,
          CONSTRAINT pk_mcp_connections PRIMARY KEY (tenant_id, server)
        )""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app.mcp_connections TO app_user")
    table = "app.mcp_connections"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} TO app_user USING ({TENANT}) WITH CHECK ({TENANT})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP SCHEMA rag CASCADE")
    op.execute("DROP SCHEMA agent_checkpoints CASCADE")
    op.execute("DROP SCHEMA eval CASCADE")
    op.execute("DROP SCHEMA ai CASCADE")
    op.execute("DROP SCHEMA jobs CASCADE")
    op.execute("DROP SCHEMA audit CASCADE")
    op.execute("DROP SCHEMA app CASCADE")
