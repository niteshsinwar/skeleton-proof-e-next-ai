---
paths:
  - "ops/**"
  - "infra/**"
  - ".github/**"
  - "**/Dockerfile"
  - "compose.yaml"
---
# Delivery and operations

**Prevents:** a working tree (with `.env`) deployed, a rollback never rehearsed, a poisoned dependency installed, and alerts nobody owns [07].

- **Build once, promote the same image digest;** never deploy a working tree [07/O1]. Migrations run from the image before traffic [07/O2]. Environments explicit; a deploy is a human action and is recorded in STATE [07/O3].
- **Deploys go through `scripts/deploy.py`** (its contract: `ops/deploy/README.md`), by digest, with the host env file outside the tree.
- Go-live preconditions refuse to start unless CI is green on the exact commit [07/O4]. Rollback designed and rehearsed; data looking wrong is never a rollback [07/O5]. Canary + automatic rollback at S/E [07/O6, 07/OL4].
- Correlation everywhere; RED + saturation signals; traces via OpenTelemetry mapped to `gen_ai.*` at export; tracing proven from the store [07/O7–O11].
- An SLO per journey with a burn-rate alert; "system down" and "AI degraded" are separate alerts with owners and runbooks; runbook steps carry a Verify line [07/O13–O16, 07/OL2, 07/OL3].
- Incidents end in a runbook entry and a failure-log hardening; expiry of certificates, tokens and models is monitored; cost per task has an alert [07/O17–O19].
- **Supply chain:** exact lockfiles, a 7-day release-age cooldown in uv, pnpm and Renovate, actions pinned to full SHAs, workflow changes reviewed, zizmor on workflows, gitleaks, osv-scanner, SAST, SBOM and image scanning [13/V3–V5, 13/SK8].
- One aggregate `gate` job is the required check [11/GL3].

## Change contract

| | |
|---|---|
| **Load first** | `ops/failure-log.md` and the runbook for the area |
| **Run** | `make check` |
| **Same commit** | runbook Verify lines; the alert's owner; the failure-log hardening |
| **Prove** | the gate or alert was seen to both pass and fail |
| **Never** | deploy from a laptop working tree; a mutable action tag; an alert without an owner |
