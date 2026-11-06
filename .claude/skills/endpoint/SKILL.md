---
description: Add or change an API endpoint the baseline way - contract first, named command, one use case, one transaction, ETag/If-Match, idempotency, object-level authorisation, route test.
argument-hint: "<resource> <command>"
---
# /endpoint: contract first, then the smallest correct route

1. **Contract:** add the operation to the OpenAPI document (named command, never `PATCH status`; RFC 9457 errors; `If-Match` on writes; idempotency key on side-effecting POSTs).
2. **Use case** in `application/`, domain rules in `domain/`; the router only parses, authorises, calls one use case and shapes the response.
3. **Tests first** (via `/feature` or the `test-author` agent): the route test naming its path, `428`/`412`/`409`, idempotent replay, the BOLA test as another user and another tenant, strict request model, the response allowlist.
4. **Implement**, then regenerate the OpenAPI snapshot and the web client in the same commit.
5. Long work returns `202` with a job; limits and quotas set for the endpoint class.

**Rules in scope:** `.claude/rules/api.md` · `.claude/rules/backend.md` · `.claude/rules/auth.md`. **Exit gate:** `make check` green and the snapshot diff shows only the intended change.
