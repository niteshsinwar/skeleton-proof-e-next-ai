# SLOs and alerts

One file per user-facing journey (`<journey>.yaml`), few and tied to the capacity assumptions in
`docs/architecture/capacity.md` (07/O13, 01/R1). Every number here is a **starter** (`starter: true`) until load tests
and production traffic have measured it.

| Command | What it does |
|---|---|
| `make slo` | Loads every file strictly and lists owners still `OPEN`. Part of the harness tests |
| `make alerts` | Writes the burn-rate alert rules to `.tools/alerts/prometheus-rules.yaml`; refuses while any owner is `@OWNER` |

## A journey file

| Key | Meaning |
|---|---|
| `journey`, `title` | the file's name (lowercase-with-hyphens) and what people call it |
| `starter`, `measured` | `starter: true` until measured; then `starter: false` and `measured: YYYY-MM-DD` |
| `window_days` | the SLO window (30) |
| `routes` | the API routes the journey uses, `METHOD /path` as the code declares them |
| `objectives.availability` | `target`: % of requests without a 5xx. 99.5 at tier S, 99.9 at tier E (07/OL2) |
| `objectives.latency` | `target` % of requests faster than `threshold_ms` (95 = p95), a histogram bucket boundary |
| `objectives.quality` | AI journeys: `target` % of judged answers that pass, for the AI `step` |

Every objective names an `owner` (who is paged) and a `runbook` (a file under `ops/runbooks/`, optionally with a
`#heading` anchor). Unknown keys, a missing owner or a runbook that doesn't exist are refused (07/O15).

## The alerts

Multiwindow, multi-burn-rate (07/O14, OL3; Google SRE Workbook, "Alerting on SLOs"), per objective:

| Severity | Budget spent | Long window | Confirmed over | Burn rate (30-day window) |
|---|---|---|---|---|
| page | 2% | 1 h | 5 min | 14.4 |
| page | 5% | 6 h | 30 min | 6 |
| ticket | 10% | 3 days | 6 h | 1 |

An alert fires when the error ratio over **both** its windows exceeds burn rate × error budget (99.5% leaves 0.005,
so the first page fires above 0.072). The short window lets it reset soon after the burning stops.

Availability and latency raise **system** alerts (`SystemDown`, `SystemSlow`); quality raises a separate
**AI quality degraded** alert (`AIQualityDegraded`), with its own owner and runbook, because the system can be up while
its answers get worse (07/O15). Static thresholds are used only for saturation and expiry (07/OL3).

**The output is Prometheus rule YAML, one option among several.** It reads OpenTelemetry's HTTP server histogram
(`http_server_request_duration_seconds`, its route, method and status labels) and an
`ai_quality_judgements_total{step, verdict}` counter the project's online grading emits. For another
monitoring system (Grafana Cloud, Datadog, CloudWatch), keep these files as the source and translate the same policy;
the windows and thresholds are computed in `scripts/slo.py` (`burn_thresholds`).

What happens when a budget is spent: [error-budget-policy.md](error-budget-policy.md).
