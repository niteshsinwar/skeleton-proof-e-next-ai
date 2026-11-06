---
paths:
  - "apps/api/src/*/integrations/**"
---
# Integrations and webhooks

**Prevents:** a vendor outage taking us down, a renamed upstream field returning silent nulls, and a script writing to production [02 §5].

- One adapter per vendor behind a port; prefer the vendor's sandbox over a fake; live sandbox tests prefix their records and clean up [02/I1].
- Every outbound call: timeout, bounded retries with jitter **and a retry budget**, circuit breaker, its own pool [02/I2].
- Never change what a downstream consumer reads (adding a key counts) [02/I3].
- Inbound webhooks: HMAC over the raw body, constant-time compare, ~5-minute window, dedupe on the id, acknowledge fast then process idempotently; Standard Webhooks both ways [02/I4, 02/BL8].
- Reconciliation jobs compare our state with theirs; drift is a finding, not a silent fix [02/I5].
- Contract tests on upstream schemas fail loudly on drift [02/I6]. Production is read-only to scripts; write methods are stubbed [02/I7].
- Each integration has a kill switch and appears in the threat model [05/SG11, 05/SG3].

## Change contract

| | |
|---|---|
| **Load first** | the port in `domain/ports.py`, the adapter and its contract tests |
| **Run** | `make check` (the sandbox lane runs only when its env var is set) |
| **Same commit** | adapter contract test; timeout/retry test; threat-model row |
| **Prove** | an injected upstream failure trips the breaker in a test |
| **Never** | an outbound call without a timeout; a fake standing in for an available sandbox |
