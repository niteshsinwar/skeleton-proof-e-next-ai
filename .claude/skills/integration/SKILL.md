---
description: Add a third-party integration or webhook - sandbox and credentials questions, a port and one adapter, timeouts and breakers, contract tests, webhook verification, reconciliation, kill switch, threat-model row.
argument-hint: "<vendor>"
---
# /integration: one vendor, one adapter, behind a port

1. Ask: is there a sandbox? Who owns the credentials? Their rate limits? How stable is the contract? What may we write? How does it fail?
2. Define the port in `domain/ports.py` from what the domain needs; write one adapter in `integrations/<vendor>/`.
3. Every call: timeout, bounded retries with jitter and a retry budget, circuit breaker, its own pool.
4. Contract tests against the sandbox (prefixed test records, cleaned up); fakes only for what the sandbox can't produce.
5. Webhooks: HMAC over the raw body, timestamp window, dedupe by id, acknowledge fast and process idempotently.
6. A reconciliation job if state is mirrored; a kill switch; a row in `docs/architecture/security.md`.

**Rules in scope:** `.claude/rules/integrations.md` · `.claude/rules/security.md`. **Exit gate:** `make check` green; an injected upstream failure trips the breaker in a test.
