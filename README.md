# skeleton proof e next ai

TODO: one sentence on the user and the job (fill in during /discover)

| | |
|---|---|
| Tier | **E** (recorded in [`docs/decisions/0001-tier-and-shape.md`](docs/decisions/0001-tier-and-shape.md)) |
| Web UI | Next.js |
| AI | yes |
| Tenancy | multi |

## Start here

1. `make setup` installs the git hooks; `make check` must be green before any feature work.
2. Open Claude Code and run `/discover`. It fills [`docs/00-brief.md`](docs/00-brief.md) and lists what is still `OPEN`.
3. Current state: [`docs/STATE.md`](docs/STATE.md). Where things go: [`CLAUDE.md`](CLAUDE.md).

## Commands

| Command | Does |
|---|---|
| `make setup` | Dependencies, local dev keys, the API contract snapshot, git hooks |
| `make check` | Everything CI runs (integration too when `TEST_DATABASE_URL` is set) |
| `make test` · `make test-db` | Offline lanes · integration on real Postgres |
| `make db-up` · `make migrate` · `make dev` | Run the API locally (Postgres in Docker) |
| `make dev-token ARGS="--sub alice"` | A local-only token for trying the API (identity only) |
| `make grant ARGS="--sub alice --role member --reason ..."` | Give someone a role in the database (the first admin); later changes go through the admin API |
| `make eval` | The eval suite |
| `make status` | Counted status: decisions, open questions, failures, rules, tests |

## Where the rules come from

This project was rendered from the engineering baseline skeleton. Rule IDs such as `[02/A5]` in
`.claude/rules/` refer to that baseline; its location and version are recorded in `.copier-answers.yml`
(`_src_path`, `_commit`). `copier update` brings later skeleton fixes into this project.

## Cost

Model and infrastructure cost estimate: `OPEN` until `/discover` records the budget (01/C4).
