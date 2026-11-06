---
paths:
  - "apps/api/src/*/api/**"
  - "packages/contracts/**"
---
# API

**Prevents:** clients driving state machines, lost updates, duplicated writes, leaky errors and broken object-level authorisation [02 §2].

- **Named commands** (`POST /orders/{id}/submit`), never `PATCH {status}` [02/A1]. Routers call one use case [02/A2].
- **One command, one transaction:** load + expected version → authorise → domain command → version+1 → audit → outbox → commit. The route commits [02/A3].
- Strong `ETag` on reads; `If-Match` required on writes (missing `428`, stale `412`); `409` only for a domain conflict [02/A4].
- **Idempotency keys** on every side-effecting POST, mandatory for agents; replay returns the same result; reuse with a different payload is rejected [02/A5].
- Errors are RFC 9457 with a stable `code` and `correlation_id`; `detail` is user-safe [02/A6]. Status-code table in this rule's tests: 404 for both unauthorised and absent [02/A7].
- Strict request models (no mass assignment); explicit response allowlists [02/A8].
- Opaque cursors with an enforced maximum page size [02/A9]. Breaking changes ship as a new version; the old route is marked with `retiring()` (`api/deprecation.py`: `Deprecation`, `Sunset`, 410 after), and `make api-diff` (oasdiff, CI's `contract` job) fails a breaking change to the snapshot until the old route's sunset has passed [02/A10].
- The OpenAPI document is the contract and the source of the generated web client; every route has an HTTP test naming its path [02/A11].
- Health shows the build SHA; readiness checks the DB, the migration head and config [02/A12].
- Limits on payload, upload, page size, time, and quotas per principal and tenant; `429` + `Retry-After` [02/A13]. Long work returns `202` + a job [02/A14].
- Outbound calls only to allowlisted hosts; third-party responses validated as untrusted [02/A15]. Endpoints that must not exist are listed and tested [02/A16].
- Object-level checks on every id-taking route (OWASP API1) [02/Z5, 02/BL9].

## Change contract

| | |
|---|---|
| **Load first** | `packages/contracts/openapi.json`, the resource's router and tests |
| **Run** | `make check` |
| **Same commit** | route test naming the path; OpenAPI snapshot; regenerated web client; BOLA test |
| **Prove** | the snapshot diff shows only the intended change |
| **Never** | a state field writable by clients; a stack trace in `detail`; a route without a test |
