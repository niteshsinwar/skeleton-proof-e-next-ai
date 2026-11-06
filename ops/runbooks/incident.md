# Incident

Anything the alerts or the people using the product say is wrong. One response for every incident, AI incidents
included: triage, contain, preserve evidence, root cause, notify, corrective test or eval, safe reactivation (07/O17).
**Every incident ends in a runbook entry and a failure-log hardening** (10/H17).

Two alerts open most incidents, and they are separate on purpose (07/O15): **system down** (availability or latency
burn, `ops/slo/`) and **AI quality degraded** (the quality SLO's burn: the system is up, its answers are
worse).

## Response

### 1. Triage

Name one incident lead. Write down, with the time: what is wrong, since when, which journeys and tenants, and which
alert or report started it. Check whether a deploy happened just before (`git log -3 -- docs/STATE.md`).

```bash
curl -fsS https://<production host>/health
echo "exit=$?"
curl -fsS https://<production host>/ready
echo "exit=$?"
```

**Verify:** the incident log has a severity, an owner, a start time, and the `/health` SHA you checked (not the one you
remember).

### 2. Contain

Stop the harm before finding the cause. Pick the smallest lever that works:
- a release broke it: [rollback.md](rollback.md) (but **data that looks wrong is never a rollback**);
- a dependency is down: its flag or circuit breaker, and the product's degraded mode stays visible to users (01/R5);
- the AI is doing harm: switch it off with its kill switch, for one step (`ai.<step>`) or everything (`ai`). The
  product still runs with AI off (01/R5). Flags are audited and need a reason; at tier E a second
  person approves the change:

  ```bash
  curl -fsS -X POST https://<production host>/admin/flags/ai/set -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" -H "Content-Type: application/json" -d '{"enabled": false, "reason": "incident <id>"}'
  echo "exit=$?"
  ```
- a credential leaked: [secret-rotation.md](secret-rotation.md).

**Verify:** the alert's short window stops burning, or the reported behaviour can no longer be reproduced;
with AI off, `GET /ai/status` shows the step switched off.

### 3. Preserve evidence

Before anything is cleaned up or redeployed: export the logs and traces for the incident window, filtered by the
correlation ids involved, and the AI attempt records (what the model was shown, asked and said) for the
affected runs. Store them where the incident record links them; never in git when they hold personal data.

**Verify:** the incident record links the exported evidence, and its time range covers the start of the incident.

### 4. Find the root cause

Reproduce it outside production (a test, a replayed request, an eval case). Ask why until the
answer is a missing control, not a person.

**Verify:** a test or command reproduces the failure, red, on the commit that was running.

### 5. Notify

Tell the people affected and the people who must know: users of the affected journeys, the product owner, and for
personal data the data protection owner within the legal deadline (personal-data breaches can carry a 72-hour clock).

**Verify:** the incident record lists who was told, when, and by whom.

### 6. Add the corrective test or eval

The fix ships with the test or eval case that would have caught it, seen red before the fix and green
after (06/T9, 06/E3).

**Verify:** the pull request shows the new test or eval case failing on the old code and passing on the
fix.

### 7. Safe reactivation

Turn back on what step 2 turned off, one lever at a time, watching the same alert.

**Verify:** the burn-rate alerts stay quiet for one long window (1 h) after each lever, and the smoke lane passes:
`make smoke BASE_URL=https://<production host>` then `echo "exit=$?"` prints `exit=0`.

### 8. Close with a hardening

Add an entry to `ops/failure-log.md` (what failed, loud or quiet, how it was detected, the hardening) and correct
this runbook or another one where a step was missing or wrong. A second occurrence of the same failure becomes a
rule, hook or test (10/H17).

**Verify:** the failure-log entry and the runbook change are committed and linked from the incident record.

## AI incidents

Each follows the response above; this is what is different (07/O17).

| Incident | Signal | Contain | Evidence and corrective eval |
|---|---|---|---|
| **Data disclosure**: an answer shows another tenant's or person's data | a user report; a grader finding personal data | kill switch `ai`; revoke the sessions involved | the attempt records; an eval case with the leaking context |
| **Unauthorised tool action**: an agent changed something no person approved | the audit trail shows a write without an approved proposal | kill switch for the step; reverse the change by a normal, audited command | the proposal and audit rows; a test that the write path refuses without approval |
| **Stale retrieval**: wrong answers from outdated or deleted documents | users report answers contradicting current documents | kill switch for the step; re-index or remove the stale source | the retrieved chunk ids per attempt; a case pinned to the corrected document |
| **Injection bypass**: content made the model ignore its instructions | the defence layer's flags; an unexpected tool call or format | kill switch for the step; quarantine the source content | the injected content; a new `injection_*` case in the dataset |
| **Model regression**: a model or prompt change made answers worse | the quality SLO burns; the nightly eval fails | switch the route back to the previous model or prompt version (`ai/models.yaml`, the agent pins) | the eval runs before and after; the eval suite re-run on every model change (07/O23) |
| **Runaway cost**: spend far above normal | the daily spend alert; tenants hitting `limits.tenant_daily_usd` | lower the cap or switch the step off; find the loop or the caller | the usage records per attempt; a test for the loop or a lower cap |
| **Bias**: answers systematically worse for a group of people | a user report; a sliced eval score | kill switch for the step if harm is ongoing | the affected cases; a sliced eval with those cases |
