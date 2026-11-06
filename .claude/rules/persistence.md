---
paths:
  - "apps/api/src/*/persistence/**"
---
# Persistence and migrations

**Prevents:** migrations that can't go down, locks that take production down, and an ORM path that skips invariants [02 §3].

- Postgres everywhere, the same engine in tests; the test DB is never the dev or demo DB [02/D1].
- Migrations from the first table; autogenerate is a candidate to review (it drops tables it doesn't know: use `include_object`); CI runs up **and** down on a scratch DB; never edit an applied migration [02/D2].
- Zero downtime: expand → backfill in batches → contract; `CREATE INDEX CONCURRENTLY`; `lock_timeout` before DDL; constraints `NOT VALID` then validated [02/D3].
- Indexes designed and verified with EXPLAIN; every FK indexed; `tenant_id` leads in tenant tables [02/D5].
- Audit is append-only (insert-only grant), hash-chained; say tamper-evident, never immutable [02/D6].
- One schema per owner, grants as the control; grant tests run as the app role [02/D7].
- Optimistic `version` columns; `SKIP LOCKED` only for queue rows [02/D14]. Repositories rebuild domain objects through constructors [02/B6].
- SQLAlchemy Core with psycopg 3 (async); prepared statements through PgBouncer 1.22+ only, else `prepare_threshold=None` [13/SK2].
- **Row-level security done right:** `FORCE ROW LEVEL SECURITY`; the app role isn't the owner and has no `BYPASSRLS`; tenant set with `SET LOCAL` inside the transaction; `USING` + `WITH CHECK`; fail closed when the tenant is unset; tests run as the app role [02/Z10].

## Change contract

| | |
|---|---|
| **Load first** | the latest migration, the repository and its tests |
| **Run** | `make check` (includes migrations up and down) |
| **Same commit** | the migration; repository tests on real Postgres; grant and RLS tests |
| **Prove** | the migration ran down and up again on a scratch DB |
| **Never** | edit an applied migration; DDL without `lock_timeout`; tests as a superuser |
