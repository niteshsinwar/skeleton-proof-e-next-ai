---
paths:
  - "apps/api/src/*/api/deps.py"
  - "apps/api/src/*/persistence/db.py"
  - "apps/api/src/*/persistence/migrations/**"
  - "apps/web/**/auth/**"
  - "apps/web/**/*session*"
---
# Auth, permissions and tenancy

**Prevents:** a forged token accepted, one user reading another's object, an agent exceeding its user, and a role trusted from the client [02 §4].

- **Verify, never mint:** tokens checked against a pinned JWKS (algorithm allowlist, `iss`, `aud`, `exp`, `nbf`); no bypass flag; unconfigured means `401` [02/Z1].
- Human login is OIDC code + PKCE (S256), exact redirect URIs, `state` and `nonce`; the provider is chosen per project by ADR, a mock OIDC server runs locally [02/Z2, 13/SK4].
- Passkeys required for privileged roles [02/Z3]. Sessions: short access tokens, public-client refresh tokens rotated or sender-constrained, re-auth for sensitive acts, revocation takes effect at once [02/Z4].
- **Authorisation is data, checked per object** before acting; never trust a client-supplied role or actor [02/Z5]. Separation of duties and no self-approval [02/Z6].
- Three principals: humans, agents acting for a user (user's permissions ∩ agent scopes), service principals; audit stores principal type and on-behalf-of [02/Z7]. Agents and MCP clients use audience-bound OAuth tokens, no passthrough [02/Z8].
- Tenancy: shared schema + `tenant_id` + row-level security (ADR) [02/Z9, 02/Z10]. **Tenant everywhere:** every row, job, cache key, log tag, rate limit, file path, vector chunk; per-tenant encrypted tool credentials [02/Z11].
- Personas change defaults and permissions, never vocabulary [02/Z12]. In the browser, tokens are never reachable from JavaScript and middleware never authorises alone [03/F9, 03/F40]. Screens learn what the caller may do from `GET /me` (the grants), never from token claims, and show people by the `name` claim (the provider must put it in access tokens), never by subject [02/Z5, 03/F16].

## Change contract

| | |
|---|---|
| **Load first** | the capability matrix and `api/deps.py` |
| **Run** | `make check` |
| **Same commit** | positive and negative permission tests, cross-tenant test, BOLA test per id-taking route [02/Z14] |
| **Prove** | the negative test fails when the check is removed |
| **Never** | a client-only permission; a long-lived token in a URL; a shared service account for all users |
