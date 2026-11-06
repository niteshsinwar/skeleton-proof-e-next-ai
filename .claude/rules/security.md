---
paths:
  - "apps/api/src/*/security/**"
  - "apps/api/src/*/integrations/webhooks/**"
  - "docs/architecture/security.md"
  - "SECURITY.md"
---
# Security (cross-cutting)

**Prevents:** the control that watches instead of removing, hostile uploads, injected instructions acting, and a feature that can't be switched off [05].

- **Remove before you watch;** every control fails closed and says how it fails [05/SG1].
- Fill in the layered safety stack in `docs/architecture/security.md` and keep the threat model current when a trust boundary moves [05/SG2, 05/SG3].
- AI risks are walked against the OWASP LLM Top 10 and Agentic Top 10 maps [05/SG4].
- **Prompt injection is assumed to succeed sometimes:** external content marked as data, the model never holds a credential, writes are proposals, output validated in code [05/SG5].
- **Uploads are hostile:** allowlist + Content-Type + magic bytes, size and decompressed-size caps, server-generated names, stored outside the web root, served through an authorised handler, scanned or disarmed where required, sandboxed parsing at E [05/SG6].
- Data classified on day one; redaction is deterministic and always runs [05/SG7, 05/SG8]. Compliance is spotted at discovery and owned by a named person [05/SG9].
- Audit entries record what actually happened, never what the UI assumed [05/SG10].
- **Kill switches** for every AI feature, side-effecting tool and integration, per tenant, without a deploy, audited [05/SG11].
- Secrets: agents can't read them; no production `.env` on laptops; rotate anything that touched git [05/SG12]. Webhooks: HMAC over the raw body, 5-minute window, dedupe by id [02/I4].

## Change contract

| | |
|---|---|
| **Load first** | `docs/architecture/security.md` |
| **Run** | `make check` |
| **Same commit** | the negative test for the control; the threat-model row if a boundary moved |
| **Prove** | the hostile input (injection, bomb, forged signature) is refused by a test |
| **Never** | a control enforced only by a prompt; a credential in a prompt or tool description |
