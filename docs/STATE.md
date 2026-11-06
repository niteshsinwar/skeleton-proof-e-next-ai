# STATE: skeleton proof e next ai

**Dated:** rendered from the skeleton; update with `/end` at the end of every session. Keep it under 6 KB, critical first (10/H14).

## What is true

- The project was rendered from the engineering baseline skeleton (tier E, UI: next, AI: yes, tenancy: multi).
- The harness is in place: rules, hooks, skills and subagents. No application code exists yet.
- `make check` covers the harness integrity check and the hook tests.

## In progress

- Nothing yet.

## Next

1. `/discover`: fill `docs/00-brief.md`, the invariants and `docs/open-questions.md`.
2. Accept or revise `docs/decisions/0001-tier-and-shape.md`.

## OPEN items that block work

- The brief: everything in `docs/00-brief.md` is `OPEN` until `/discover` runs.

## Deploys (07/O3)

Each deploy and rollback, from its record (deploy.yml's job summary, or `scripts/deploy.py`'s JSON): `/release` adds the row.

| When (UTC) | Env | Action and result | SHA | Migration | Approved and run by |
|---|---|---|---|---|---|

## Operating record (latest session)

- None yet.
