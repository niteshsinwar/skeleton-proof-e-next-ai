---
description: Review a change through six lenses (product, frontend, backend and system design, security, accessibility and testing, cloud and ops) on one severity scale. Critical blocks; High is fixed before merge.
argument-hint: "[path or diff range]"
---
# /review: six lenses, one severity scale

Run the read-only `spec-reviewer` and `security-reviewer` agents and review each lens yourself. Report each finding with its severity, location, evidence and fix.

| Lens | Asks |
|---|---|
| Product designer | Is it a journey step for a named persona? Copy, empty states, the reader's vocabulary? |
| Frontend engineer | Rendering choice, budgets, states, generated client, no literal values? |
| Backend and system designer | Layering, one transaction per command, idempotency, push vs poll, caching, load on the backend? |
| Security | Object-level authorisation, secrets, injection, uploads, CSP and CSRF, audit truthfulness? |
| Accessibility and tester | axe and keyboard; red-first tests; **honest fixtures** (read the fixture; no assertion that accepts either answer); mutation on critical paths? |
| Cloud and ops | Built artefact, migrations, headers, observability, rollback, cost? |

| Severity | Means |
|---|---|
| Critical | blocks the merge |
| High | fixed before merge |
| Medium | fixed or ticketed |
| Low | optional |

Also check the placement: did the change extend what exists, or start a parallel structure?
