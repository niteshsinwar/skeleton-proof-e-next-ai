# Load tests (k6)

Load is tested, not assumed (01/R9). k6 runs each scenario against a base URL and exits non-zero when a threshold is
crossed (99 for a threshold, 107 for a script error), so `make` and CI fail with it.

| Command | Scenario |
|---|---|
| `make load-smoke BASE_URL=...` | `smoke.js`: two people reading for 15 s; health, readiness, one read journey. Every change |
| `make load-mixed BASE_URL=...` | `mixed.js`: 20 reads per second from five people while one agent sends 15 per second, a rate a person may use but an agent may not. People keep their p95 and never see a 429; the agent is limited with 429 + `Retry-After` (01/R3, R4) |

Run them against a local API (`make dev`, which uses the Postgres rate limiter at tiers S and E) or the `prod`
compose stack. Locally the targets mint dev tokens for five people and one agent acting for one of them; against a
deployed environment pass real tokens instead: `HUMAN_TOKENS` (comma-separated) and `AGENT_TOKEN`. Dev tokens are
issued by `TOKEN_ISSUER` (default `local-dev`, matching the API's `APP_AUTH_ISSUER`).

**Every number here is a starter** (01/R1): rates, durations and p95 limits come from no measurement yet. Measure a
baseline, write the capacity assumptions in `docs/architecture/capacity.md`, then set the thresholds from them. A
threshold is a gate only if it was seen both passing and failing (01/R9): tighten it once and watch the run fail.

Spike and soak scenarios before major releases (01/R9) are added when the project has its capacity assumptions.
