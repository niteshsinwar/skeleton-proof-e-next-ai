---
paths:
  - "apps/api/src/*/security/rate*"
  - "tests/load/**"
---
# Scale and resilience (humans and agents)

**Prevents:** one agent's burst starving people, retries amplifying an outage, and capacity discovered in production [01 §3].

- Capacity assumptions are written down (humans and agents, peaks, read/write mix, latency targets, growth, budget) in `docs/architecture/capacity.md` [01/R1].
- Rate limits and quotas are layered: per principal, tenant and endpoint class, with cost units; token bucket or GCRA; fail-open or fail-closed written per class; `429` + `Retry-After` [01/R2, 01/AL2].
- Process-local state (an in-process limiter, a cache) is valid only with a single instance; several instances share a store [01/T6, 02/J5].
- Agents are their own traffic class; humans are protected first [01/R3]. Shed by priority (human > agent > batch); never shed safety, audit or approvals [01/R4, 01/AL3].
- Degrade gracefully: cached reads, the product runs with AI switched off, degraded mode visible [01/R5].
- Bulkheads, propagated deadlines and retry budgets [01/R6]. Climb the DB and caching ladders one rung at a time on a measured trigger [01/R7, 01/R8].
- Load is tested: k6 thresholds from a measured baseline, verified to pass and to fail [01/R9, 01/AL4].

## Change contract

| | |
|---|---|
| **Load first** | `docs/architecture/capacity.md` |
| **Run** | `make check` (plus the k6 smoke at tier S/E) |
| **Same commit** | limiter tests per class; capacity doc if an assumption changed |
| **Prove** | a mixed human/agent load keeps the human p95 while agents get `429` |
| **Never** | add infrastructure without its trigger and an ADR [01/R10] |
