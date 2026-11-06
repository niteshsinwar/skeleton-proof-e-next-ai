---
paths:
  - "apps/api/src/*/workflow/**"
  - "apps/api/src/*/jobs/**"
---
# Workflow, jobs, events and schedules

**Prevents:** a transaction held across a model call, duplicate side effects, stuck jobs nobody reaps, and late output from a superseded run [02 §6].

- Pick the flow by duration and audience: sync under a few seconds; a job beyond ~10 s; events for many consumers; scheduler → orchestrator → workers for batches [01/T2].
- Workflow state is named states entered by named commands; holds are intervals [02/D13]. The state machine is deterministic; no model call decides a transition.
- No unit of work across a provider call: gather, call, re-check the version, write [02/J1].
- DB-backed queue behind the `JobQueue` port: business idempotency key, bounded retries, visible dead letter, visibility timeout, a reaper that doesn't depend on traffic; the library must pass the job-contract spike [02/J2, 13/SK6].
- A broker joins only when the database queue's throughput or fan-out is measured to fall short [01/T4]. Optimistic versions on aggregates, idempotency keys on retried writes [01/T5].
- Events through the outbox after commit; idempotent consumers; per-entity sequence numbers; versioned schemas [02/J3, 01/T3].
- Schedules: single-run lock, written missed-run policy, explicit time zone, idempotent bodies [02/J4].
- A generation id fences late output; fan-out reconciles dispatched against returned [02/J6, 02/J7].
- Agent runs are durable and resumable: state after every model call, no side effects before an interrupt, preconditions re-validated on resume [04/G6].

## Change contract

| | |
|---|---|
| **Load first** | the state diagram and the handler registry |
| **Run** | `make check` |
| **Same commit** | transition tests (legal and illegal); idempotency replay test; reaper test |
| **Prove** | an illegal command leaves no partial state and writes no audit |
| **Never** | a `PATCH status`; a job without an idempotency key; a reaper that runs only on traffic |
