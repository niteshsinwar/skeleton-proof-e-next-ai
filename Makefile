# One command surface for people, Claude and CI (10/L2). Every target exists and says what it did.
# Every recipe runs in bash with -e and pipefail, so a failing step fails the target, even inside a pipe like
# `pytest | tail` (10/H13); `make harness-check` refuses a Makefile without it. The flags sit in SHELL itself,
# because macOS ships GNU make 3.81, which ignores .SHELLFLAGS.
SHELL := /bin/bash -e -o pipefail
PY ?= python3
API := apps/api
UV := uv --project $(API)
TOOLS := .tools/bin
# The images built for this commit (07/O1): `make image` builds them, `sbom` and `scan-image` describe and scan them.
SHA = $$(git rev-parse --short HEAD)
WEB := apps/web
PNPM := pnpm --dir $(WEB)

.PHONY: api-diff help setup setup-api setup-web hooks dev worker check test test-api test-web test-db image test-image sbom scan-image mutation lint lint-api lint-web types types-api types-web tools security secrets deps sast workflows workflow-check ci-databases expiry-check eval eval-selftest status harness-check harness-test contracts migrate db-up db-down dev-token grant verify-audit test-e2e dev-web dev-issuer

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' Makefile | sed -E 's/:.*## /\t/'

setup: setup-api setup-web hooks ## Install everything: dependencies, local dev keys, the API contract snapshot, the web client, the e2e browser and the git hooks
	@echo "setup: done"

setup-api: ## The backend: dependencies from the lockfile (CI only checks it, never rewrites it), dev keys, contract snapshot
	@if [ "$$CI" = "true" ]; then $(UV) lock --check; else $(UV) lock --quiet; fi
	@$(UV) sync --locked --quiet
	@$(UV) run python scripts/dev_token.py --sub setup --init-only
	@test -f packages/contracts/openapi.json || $(MAKE) -s contracts

setup-web: ## The web app: dependencies from the lockfile (frozen in CI), the generated client, the e2e browser
	@$(PNPM) install --loglevel=error
	@$(PNPM) -s gen:api
	@$(PNPM) exec playwright install $$( [ "$$CI" = "true" ] && echo --with-deps ) chromium

hooks: ## Install the git hooks (13/SK9): commit message, granularity guard, secret scan on staged files
	@if command -v prek >/dev/null 2>&1; then prek install --hook-type pre-commit --hook-type commit-msg; \
	elif command -v pre-commit >/dev/null 2>&1; then pre-commit install --hook-type pre-commit --hook-type commit-msg; \
	else echo "hooks: install prek to enable the git hooks (13/SK9)"; fi

dev: ## Run the API locally (needs `make db-up` and `make migrate`; reads .env)
	@cd $(API) && uv run uvicorn --app-dir src --env-file ../../.env --factory --reload skeleton_proof_e_next_ai.api.app:create_app

worker: ## Run the job worker: outbox relay, jobs and the reaper (needs `make db-up` and `make migrate`; reads .env)
	@cd $(API) && uv run --env-file ../../.env python -m skeleton_proof_e_next_ai.jobs

dev-issuer: ## Run the local MOCK OIDC issuer the web app signs in through (development only)
	@cd $(API) && uv run python ../../scripts/mock_oidc.py --port 9400 --client web:local-dev-secret:http://127.0.0.1:3000/auth/callback

dev-web: ## Run the web app locally (needs `make dev` and `make dev-issuer`; reads .env)
	@set -a && . ./.env && set +a && $(PNPM) dev

check: harness-check harness-test workflow-check lint types test ## Everything CI runs except the scans (their own job); the Stop gate runs this too
	@if [ -n "$$TEST_DATABASE_URL" ] || [ "$$REQUIRE_DB" = "1" ]; then $(MAKE) -s test-db; \
	else echo "check: integration lane skipped (set TEST_DATABASE_URL; CI sets REQUIRE_DB=1)"; fi
	@if [ "$$REQUIRE_DOCKER" = "1" ]; then $(MAKE) -s test-image; \
	else echo "check: image lane skipped (make test-image runs it with Docker; CI sets REQUIRE_DOCKER=1)"; fi
	@if [ -n "$$E2E_DATABASE_URL" ] || [ "$$REQUIRE_E2E" = "1" ]; then $(MAKE) -s test-e2e; \
	else echo "check: e2e lane skipped (set E2E_DATABASE_URL; CI sets REQUIRE_E2E=1)"; fi
	@$(MAKE) -s mutation
	@echo "check: all green"

test: harness-test test-api test-web ## Free, offline lanes: unit, invariant, contract, the eval harness's self-test (06/T1)

test-api: ## The backend's free, offline lanes and the eval harness's self-test
	@cd $(API) && uv run pytest -m "not integration"
	@$(MAKE) -s eval-selftest

test-web: ## The web app's unit tests
	@$(PNPM) -s test

image: ## Build the images once, tagged with this commit (07/O1); the same digest is promoted, never rebuilt
	@docker build -f $(API)/Dockerfile --build-arg BUILD_SHA=$$(git rev-parse HEAD) -t skeleton-proof-e-next-ai-api:$$(git rev-parse --short HEAD) .
	@docker build -f $(WEB)/Dockerfile --build-arg BUILD_SHA=$$(git rev-parse HEAD) -t skeleton-proof-e-next-ai-web:$$(git rev-parse --short HEAD) .

sbom: ## A CycloneDX SBOM of each image built for this commit (07/O21, 13/SK8); run `make tools image` first
	@$(TOOLS)/syft skeleton-proof-e-next-ai-api:$(SHA) -q -o cyclonedx-json=sbom-api.cdx.json && echo "sbom: wrote sbom-api.cdx.json"
	@$(TOOLS)/syft skeleton-proof-e-next-ai-web:$(SHA) -q -o cyclonedx-json=sbom-web.cdx.json && echo "sbom: wrote sbom-web.cdx.json"

scan-image: ## Fail on a fixable high or critical vulnerability in the images built for this commit (05/SG13, 13/SK8)
	@$(TOOLS)/grype skeleton-proof-e-next-ai-api:$(SHA) --fail-on high --only-fixed -q
	@$(TOOLS)/grype skeleton-proof-e-next-ai-web:$(SHA) --fail-on high --only-fixed -q

test-image: ## Image lane: contents, start-up refusals, /health SHA, migrations run from the image (07/O1, O2); needs Docker
	@cd $(API) && uv run pytest -p no:cacheprovider ../../tests/image

test-db: ## Integration lane on real Postgres; REQUIRE_DB=1 makes a missing database an error (06/T1)
	@cd $(API) && REQUIRE_DB=1 uv run pytest -m integration

test-e2e: ## Journeys, axe, headers and Web Vitals on the BUILT web app, against the API on its own database (03/F24)
	@test -n "$$E2E_DATABASE_URL" || { echo "test-e2e: set E2E_DATABASE_URL (a database used only by this lane)"; exit 1; }
	@cd $(API) && APP_DATABASE_URL="$$E2E_DATABASE_URL" uv run alembic upgrade head
	@cd $(API) && PYTHONPATH=src uv run python ../../scripts/grant_role.py --database "$$E2E_DATABASE_URL" --tenant 00000000-0000-0000-0000-000000000001 --sub alice --role member --reason "e2e demo user" >/dev/null
	@cd $(API) && PYTHONPATH=src uv run python ../../scripts/grant_role.py --database "$$E2E_DATABASE_URL" --tenant 00000000-0000-0000-0000-000000000001 --sub bob --role approver --reason "e2e demo user" >/dev/null
	@cd $(API) && PYTHONPATH=src uv run python ../../scripts/grant_role.py --database "$$E2E_DATABASE_URL" --tenant 00000000-0000-0000-0000-000000000001 --sub root --role admin --reason "e2e demo user" >/dev/null
	@cd $(API) && uv run python ../../scripts/mock_oidc.py --publish-only
	@$(PNPM) -s build
	@$(PNPM) -s exec playwright test

mutation: ## Plant each critical fault in scripts/mutations.toml and prove its test catches it (06/T7); part of check at tier E
	@$(PY) -I scripts/mutation_check.py $(ARGS)

lint: lint-api lint-web ## Lint everything (02/B10, 13/SK2)

lint-api: ## ruff, including the async and security rules (02/B10, 13/SK2)
	@cd $(API) && uv run ruff check src tests ../../tests ../../evals
	@cd $(API) && uv run ruff format --check src tests ../../tests ../../evals

lint-web: ## ESLint and Prettier on the web app
	@$(PNPM) -s lint

types: types-api types-web ## Type-check everything (02/B10)

types-api: ## mypy --strict on the backend (02/B10)
	@cd $(API) && uv run mypy

types-web: ## tsc on the web app
	@$(PNPM) -s typecheck

tools: ## Install the pinned scanners into .tools/bin, each checked against its sha256 (ops/tools.toml, 13/V3)
	@$(PY) -I scripts/tools.py

security: secrets deps sast workflows ## Every security gate CI runs (05/SG13, 13/SK8); run `make tools` first
	@echo "security: all gates passed"

secrets: ## gitleaks over this repository's whole history (or the working tree when it is not its own repository), ai/ and evals/ included (05/SG12)
	@if [ "$$(git rev-parse --show-toplevel 2>/dev/null)" = "$$(pwd -P)" ]; then $(TOOLS)/gitleaks git --redact --no-banner --config .gitleaks.toml .; \
	else $(TOOLS)/gitleaks dir --redact --no-banner --config .gitleaks.toml .; fi

deps: ## osv-scanner over both lockfiles: a known vulnerability in any pinned dependency fails (07/O21)
	@mkdir -p .tools
	@$(UV) export --frozen --all-groups --no-hashes --format requirements-txt --quiet -o .tools/requirements.txt
	@$(TOOLS)/osv-scanner scan source --lockfile requirements.txt:.tools/requirements.txt --lockfile $(WEB)/pnpm-lock.yaml

sast: ## Semgrep CE rules for Python, TypeScript and Dockerfiles; a finding fails unless reviewed in place (05/SG13)
	@uvx --exclude-newer "7 days" semgrep==1.182.1 scan --metrics off --error --quiet --config p/python --config p/typescript --config p/dockerfile apps

workflows: workflow-check ## The workflows: our structural guard, then zizmor's audit (13/V5)
	@uvx --exclude-newer "7 days" zizmor==1.31.1 --offline --min-severity medium .github/workflows

workflow-check: ## Actions pinned by SHA, read-only token, no pull_request_target, one gate needing every job (13/V5, 11/GL3)
	@$(PY) -I scripts/workflow_check.py

ci-databases: ## CI only: one database per lane in the compose Postgres, never shared (06/T10)
	@docker compose exec -T postgres createdb -U app_owner ci_test
	@docker compose exec -T postgres createdb -U app_owner ci_e2e

eval: ## Run every released dataset LIVE, each case 3+ times, recorded (needs the key, EVAL_LIVE=1, APP_DATABASE_URL)
	@cd $(API) && uv run pytest -c ../../evals/pytest.ini ../../evals/test_datasets.py $(ARGS)

eval-selftest: ## The eval harness proves its own verdicts both ways, offline (06/E7); never an eval
	@cd $(API) && uv run pytest -c ../../evals/pytest.ini ../../evals/harness/tests

expiry-check: ## Fail on what lapses soon: a model retiring within 30 days, a TLS certificate of EXPIRY_HOSTS within 21 (07/O18, O23)
	@cd $(API) && PYTHONPATH=src uv run python ../../scripts/expiry_check.py $(ARGS)

status: ## Counted status (never estimated, 12/N9)
	@$(PY) -I scripts/status.py

harness-check: ## Harness integrity: rule frontmatter, references, budgets, hook wiring (10/H1-H5, H12)
	@$(PY) -I scripts/harness_check.py

harness-test: ## Harness tests: hooks and harness scripts, both directions (10/H12)
	@$(PY) -I -m unittest discover -s .claude/hooks/tests -p 'test_*.py'

contracts: ## Regenerate the committed OpenAPI snapshot and the web client (02/A11, 12/N6); commit them with the route change
	@cd $(API) && PYTHONPATH=src uv run python -c "import json, pathlib; from skeleton_proof_e_next_ai.api.app import create_app; from skeleton_proof_e_next_ai.config.settings import Settings; spec = create_app(Settings(env='test')).openapi(); p = pathlib.Path('../../packages/contracts/openapi.json'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(spec, indent=2, sort_keys=True) + '\n'); print('contracts: wrote', p)"
	@if [ -d $(WEB)/node_modules ]; then $(PNPM) -s gen:api; fi

api-diff: ## Fail on a breaking change to the committed OpenAPI snapshot since BASE (default origin/main), with oasdiff (02/A10)
	@$(PY) -I scripts/api_diff.py --base "$(or $(BASE),origin/main)"

migrate: ## Apply migrations (an explicit step, before new code takes traffic, 07/O2)
	@cd $(API) && uv run --env-file ../../.env alembic upgrade head

db-up: ## Start local Postgres (Docker)
	@docker compose up -d --wait postgres

db-down: ## Stop local Postgres
	@docker compose down

dev-token: ## Mint a local-only token (identity only; roles come from grants): make dev-token ARGS="--sub alice"
	@$(UV) run python scripts/dev_token.py $(ARGS)
verify-audit: ## Verify the audit hash chain independently (02/D6); exits 1 at the first break
	@cd $(API) && uv run --env-file ../../.env python ../../scripts/verify_audit_chain.py
grant: ## Grant or revoke a role in the database, e.g. the first admin: make grant ARGS="--sub alice --role admin --reason ..."
	@cd $(API) && PYTHONPATH=src uv run --env-file ../../.env python ../../scripts/grant_role.py $(ARGS)

# Operate (B5-6)
.PHONY: reference-freshness link-check slo alerts load-smoke load-mixed test-pooler

reference-freshness: ## Every note in .claude/reference/ was verified within 21 days (10/H17); run nightly
	@$(PY) -I scripts/reference_freshness.py

link-check: ## Every relative link in the Markdown leads to a file and heading that exist (offline); run nightly
	@$(PY) -I scripts/link_check.py

# Dev tokens for the load scenarios: five people and one agent acting for the first (identity only; local APIs only).
TOKEN_ISSUER ?= local-dev
LOAD_HUMANS = $$(for i in 1 2 3 4 5; do $(UV) run python scripts/dev_token.py --sub load-human-$$i --issuer $(TOKEN_ISSUER); done | paste -sd, -)
LOAD_AGENT = $$($(UV) run python scripts/dev_token.py --sub load-agent --act-for load-human-1 --issuer $(TOKEN_ISSUER))
# The pooler proof's PgBouncer (ops/pooler/), in front of the compose Postgres; local-only credentials.
POOLER_URL := postgresql+psycopg://app_owner:local-only-not-a-secret@127.0.0.1:6432/app

slo: ## Load every SLO in ops/slo strictly; lists the alert owners still OPEN (07/O13-O15)
	@$(PY) -I scripts/slo.py check

alerts: ## Write the burn-rate alert rules (Prometheus format) to .tools/alerts/; refuses an alert without a named owner (07/O14, O15)
	@$(PY) -I scripts/slo.py alerts --out .tools/alerts/prometheus-rules.yaml $(ARGS)

load-smoke: ## k6 smoke load against BASE_URL; a crossed threshold fails the run (01/R9). Needs `make tools`
	@test -n "$(BASE_URL)" || { echo "load-smoke: set BASE_URL, e.g. make load-smoke BASE_URL=http://127.0.0.1:8000"; exit 2; }
	@HUMAN_TOKENS="$${HUMAN_TOKENS:-$(LOAD_HUMANS)}" $(TOOLS)/k6 run --quiet -e BASE_URL="$(BASE_URL)" tests/load/smoke.js

load-mixed: ## k6 people + agent traffic against BASE_URL: people keep their p95, the agent gets 429 (01/R3, R4, R9)
	@test -n "$(BASE_URL)" || { echo "load-mixed: set BASE_URL, e.g. make load-mixed BASE_URL=http://127.0.0.1:8000"; exit 2; }
	@HUMAN_TOKENS="$${HUMAN_TOKENS:-$(LOAD_HUMANS)}" AGENT_TOKEN="$${AGENT_TOKEN:-$(LOAD_AGENT)}" $(TOOLS)/k6 run --quiet -e BASE_URL="$(BASE_URL)" tests/load/mixed.js

test-pooler: ## Prepared statements work through PgBouncer >= 1.22 in transaction mode (01/R7); the CI pooler job. Needs Docker
	@docker compose -f compose.yaml -f ops/pooler/compose.yaml up -d --wait postgres pgbouncer
	@cd $(API) && REQUIRE_POOLER=1 TEST_DATABASE_URL="$(POOLER_URL)" POOLER_DATABASE_URL="$(POOLER_URL)" uv run pytest -m integration tests/integration/test_pooler.py

# Deploy and release (B5-5)
# The deploy contract and its Docker host adapter (scripts/deploy.py, ops/deploy/README.md): the BUILT images by
# digest, never a working tree (07/O1); migrations from the image before traffic (07/O2); production behind the
# go-live preconditions (07/O4); a failed smoke reverts to the previous digest (07/O6); every deploy recorded (07/O3).
# The host env file is DEPLOY_ENV_FILE or /etc/skeleton-proof-e-next-ai/<env>.env, never this tree.
.PHONY: publish deploy rollback go-live-check deploy-status smoke rehearse-rollback restore-drill

DEPLOY := $(PY) -I scripts/deploy.py

publish: ## Build this commit's images once and push by digest: make publish REGISTRY=ghcr.io/owner (deploy.yml runs it)
	@test -n "$(REGISTRY)" || { echo "publish: set REGISTRY, e.g. ghcr.io/owner"; exit 2; }
	@$(DEPLOY) publish --registry "$(REGISTRY)" --sha "$$(git rev-parse HEAD)" $(ARGS)

deploy: ## Deploy by digest: make deploy ENV=staging|production DIGEST=sha256:... WEB_DIGEST=sha256:... (production runs go-live-check first)
	@$(DEPLOY) deploy --env "$(ENV)" --api-image "$(DIGEST)" --web-image "$(WEB_DIGEST)" $(ARGS)

rollback: ## Back to an older release, one migration step at a time: make rollback ENV=... TO=<digest> (07/O5)
	@$(DEPLOY) rollback --env "$(ENV)" --to "$(TO)"$(if $(WEB_TO), --web-to "$(WEB_TO)") $(ARGS)

go-live-check: ## Refuse unless CI is green on the commit, the images exist, secrets are set, the JWKS is public, rollback is known (07/O4)
	@$(DEPLOY) go-live-check --env "$(ENV)" --api-image "$(DIGEST)" --web-image "$(WEB_DIGEST)" $(ARGS)

deploy-status: ## What runs in an environment, and its release record: make deploy-status ENV=...
	@$(DEPLOY) status --env "$(ENV)"

smoke: ## Read-only checks against a deployed environment: make smoke BASE_URL=... WEB_URL=... [EXPECT_SHA=...] (06/T1, 07/O3)
	@$(PY) -I tests/smoke/smoke.py --base-url "$(BASE_URL)" --web-url "$(WEB_URL)"$(if $(EXPECT_SHA), --sha "$(EXPECT_SHA)")

rehearse-rollback: ## On local Docker: deploy N, migrate, deploy N+1, roll back one migration step at a time, prove /ready and the data (07/O5)
	@cd $(API) && PYTHONPATH=src uv run python ../../scripts/drills.py rehearse-rollback

restore-drill: ## On local Docker: dump, restore to a scratch database, prove /ready and the data and the audit chain (07/O20, 02/D15)
	@cd $(API) && PYTHONPATH=src uv run python ../../scripts/drills.py restore-drill
