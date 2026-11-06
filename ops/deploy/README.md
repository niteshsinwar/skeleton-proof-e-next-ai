# Deploy targets: the contract, the Docker host adapter, and the slot for a cloud

One pipeline, many targets (plans/b5 §1.3): build once, push by digest, migrate, deploy, smoke, record. Only a small
**target adapter** differs. The skeleton builds one, the **Docker host running Compose** (`compose-host`), because it
runs end to end on local Docker and so carries the rollback rehearsal and the restore drill. A cloud is the project's
choice; this page is what its adapter must do. Nothing here has been run against a real cloud (README #12).

## What exists

| Part | Where | Proof |
|---|---|---|
| The contract and the `compose-host` adapter | `scripts/deploy.py` (stdlib, JSON out) | `apps/api/tests/unit/test_deploy.py`: each go-live precondition refusing and passing, the revert, the rollback, the dry run, idempotence, offline |
| The production stack | `compose-host/compose.yaml` | the BUILT images by digest; `migrate` as a one-off before traffic; healthchecks on `/ready`; the worker's drain time; Postgres managed (URLs) or bundled (`DEPLOY_DATABASE=bundled`, a named volume) |
| The host env file | `compose-host/host.env.example` (names only) | refused when inside the repository, readable by others, or for another environment |
| Post-deploy smoke | `tests/smoke/smoke.py` (`make smoke`) | read-only; `apps/api/tests/unit/test_smoke.py` |
| Rehearsals on local Docker | `scripts/drills.py` (`make rehearse-rollback`, `make restore-drill`) | N → N+1 → N one migration step at a time with no row lost; the half-migrated replay caught by `/ready`; a failed smoke reverted; a private JWKS refused; dump, restore, `/ready` and the data and the audit chain from the scratch copy |
| The pipeline | `.github/workflows/deploy.yml` | linted by `make workflows`; **not yet run on GitHub** (B5-7) |

## The contract (what every adapter implements)

| Command | Does | Must |
|---|---|---|
| `deploy --env E --api-image REF --web-image REF` | run the go-live preconditions (production) or the preflight (staging), migrate from the new image, start it, smoke it, record it | refuse a tag (digests only); leave a running, healthy release alone; on a failed smoke **revert to the previous digest** (07/O6) |
| `migrate --env E --api-image REF` | `python -m skeleton_proof_e_next_ai.run migrate` from the image, as the schema owner, before traffic (07/O2) | never with the app's credential (02/Z10) |
| `status --env E` | what runs, its health, and the release record (SHA, migration, images, previous images, who, when) | read only |
| `rollback --env E --to REF` | step the schema down **with the image now running** (`run downgrade --to <target's head>`, one step at a time), then start the target and smoke it (07/O5) | never `downgrade base`; refuse when nothing runs |
| `shift --percent N` (optional) | send a share of traffic to the new release, for a canary (07/O6) | only where the target can split traffic; a single Compose host can't, so it reverts instead |

Every command prints **one JSON document** on stdout and its steps on stderr, exits 0 only on success, takes
`--dry-run` (prints the plan, changes nothing) and is idempotent. Images are `REPOSITORY@sha256:<digest>`; the
`org.opencontainers.image.revision` label names the commit, and `/health` must show it (02/A12). Secrets reach the
target from its own store, never from the repository, and never on a command line.

## Adding a cloud target (the `infra/` slot)

1. Write the infrastructure in `infra/` (an ADR names the tool; OpenTofu was the recommendation, plans/b5 D7):
   the runtime service, the database, the registry pull permission, the secret store, the network.
2. Add an adapter class beside `ComposeHost` in `scripts/deploy.py` with the commands above, chosen by `--target`.
   Typical mappings: Cloud Run (`gcloud run deploy --image REF`, a job for `migrate`, revisions and traffic tags for
   `shift`), ECS Fargate (a task definition revision per digest, a one-off task for `migrate`, CodeDeploy for
   `shift`), Azure Container Apps (revisions, a job for `migrate`, revision weights for `shift`).
3. Trust the cloud from `deploy.yml` with **OIDC** (`permissions: id-token: write` on the deploy job only, a role
   bound to this repository and environment): no stored cloud keys (13/V5).
4. Prove it as this adapter was proved: the contract tests against a fake of the cloud's CLI, a dry run in CI, and
   then a real staging deploy, recorded in `docs/STATE.md`. Until that deploy, label it "not yet run against a real
   <cloud>" (README #12).
