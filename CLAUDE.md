# skeleton proof e next ai: working agreement

TODO: one sentence on the user and the job (fill in during /discover)

Tier **E** · UI: next · AI: yes · Tenancy: multi

This file is a navigation index, not a manual (10/H1). Area rules load from `.claude/rules/` when you
touch matching files. IDs such as `[02/A5]` cite the engineering baseline this project was rendered
from; the text of every rule cited is pinned in `.claude/reference/baseline-rules.md`.

## Read first

1. `docs/STATE.md`: dated current truth (the session-start hook injects it).
2. `docs/00-brief.md` and `docs/open-questions.md`: nothing load-bearing is built on an `OPEN` item.
3. The rule for the area you are about to touch.

## Commands

| Command | When |
|---|---|
| `make setup` | Once: dependencies, local dev keys, the API contract snapshot, git hooks |
| `make check` | Before saying anything is done; the Stop gate runs it too |
| `make test` | Free offline lanes: unit, invariant, contract |
| `make test-db` | Integration on real Postgres (needs `TEST_DATABASE_URL`) |
| `make contracts` | After any API change: regenerate the OpenAPI snapshot and commit it |
| `make db-up` · `make migrate` · `make dev` | Run the API locally against Postgres in Docker |
| `make worker` | Run the job worker (outbox relay, jobs, reaper) beside `make dev` |
| `make dev-issuer` · `make dev-web` | Sign-in through the local mock issuer, and the web app |
| `make test-e2e` | Journeys, axe, headers, Web Vitals on the built web app (needs `E2E_DATABASE_URL`) |
| `make eval` | The eval suite |
| `make status` | Counted status; quote it instead of estimating |
| `make harness-check` | After changing anything in `.claude/` |

## Where a new thing goes

| Adding | Goes in | Skill |
|---|---|---|
| Endpoint | `apps/api/src/<pkg>/api/routers/` + `application/` | `/endpoint` |
| Screen | `apps/web/` route + `components/<area>/` | `/screen` |
| Entity or table | `domain/` + `persistence/` + migration | `/data-model` |
| Integration | `integrations/<vendor>/` + a port | `/integration` |
| AI step or agent | `ai/agents/<agent>/<version>.yaml` + `intelligence/` | `/ai-step` |
| Any other feature | spec in `docs/specs/<feature>/` first | `/feature` |
| Decision | `docs/decisions/NNNN-*.md` | `/adr` |
| Failure | `ops/failure-log.md`, then its hardening | `/failure-log` |
| Verified external fact | `.claude/reference/` (dated, with source) | `researcher` agent |

Extend what exists before creating anything new; never build a parallel structure (10/H19).

## Workflow skills

- Start and end: `/start` · `/discover` · `/status` · `/end`
- Build: `/feature` · `/endpoint` · `/screen` · `/data-model` · `/integration` · `/ai-step`
- Check: `/review` · `/audit` · `/check-fixtures` · `/threat-model` · `/scorecard`
- Record and ship: `/adr` · `/failure-log` · `/release`

## The non-negotiables (full list: `.claude/rules/00-invariants.md`)

- Guarantees live in code, tests and hooks, never only in prose.
- Fail closed. No silent fallbacks. Unknown configuration keys raise.
- Model output is untrusted input. Consequential writes are proposals with an idempotency key.
- Secrets never enter git, images, logs or chat.
- Production is read-only to agents. Deploys are human actions.

## Stop and ask

Ask before acting when the answer changes the work and has no safe default: scope, who decides or
approves, anything irreversible, money, personal or regulated data, security posture, infrastructure
facts, AI quality thresholds, or an external fact without a source. Ask one decision at a time, with
options, consequences and a recommendation. Record the answer as `USER-DECISION` so it is never
asked twice.

Always confirm first: deploys, production migrations, deleting data, sending messages, spending
money, pushing.

Don't ask about conventional defaults or anything already decided (read the ADRs and STATE first).

## Order of trust

Running code and live systems > dated docs > architecture docs > comments and chat (10/H6).
