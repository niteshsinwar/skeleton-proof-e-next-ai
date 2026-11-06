# A2A, the Agent2Agent protocol (verified 2026-11-05)

What the outside-agent rule relies on. Nothing here is built; re-verify before building on it (10/H17, H20).

| Fact | Status | Source |
|---|---|---|
| Latest released version 1.0.0 (earlier 0.3.0, 0.2.6, 0.1.0); the page itself carries no date | READ | a2a-protocol.org/latest/specification |
| Governed under the Linux Foundation since June 2025 (started at Google, April 2025) | RETRIEVED | secondary articles; not on the spec page |
| The Agent Card is at `https://{server_domain}/.well-known/agent-card.json`; it declares `securitySchemes` and `security` | READ | specification §8.2, §4.5 |
| Operations: Send Message, Send Streaming Message, Get Task, List Tasks, Cancel Task, Subscribe to Task, push-notification config (create, get, list, delete), Get Extended Agent Card | READ | specification |
| Production MUST use HTTPS/TLS; credentials go in protocol headers on every request; the server MUST authenticate every request, MUST reject missing or invalid credentials, and MUST NOT reveal resources the client may not access | READ | specification §7.1–7.4 |
| In-task auth: the task moves to `TASK_STATE_AUTH_REQUIRED`; credentials arrive out of band; that state is never authorisation by itself; in-band exchange "can allow credentials to be passed across chains of multiple A2A agents" | READ | specification §7.6 |
| Agent Cards MAY be signed with JWS (RFC 7515) over the JCS-canonicalised card (RFC 8785, `signatures` excluded); header has `alg` and `kid`; clients SHOULD verify one signature before trusting a card; expired or revoked keys MUST NOT verify | READ | specification §8.4 |
| The spec's text on treating another agent's content as untrusted was not found in what was read | OPEN | the last quarter of the specification page was not read |
