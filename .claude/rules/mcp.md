---
paths:
  - "ai/mcp-servers.yaml"
  - "apps/api/src/*/intelligence/mcp.py"
  - "apps/api/src/*/application/outside_tools.py"
  - "apps/api/src/*/api/mcp.py"
---
# MCP: outside tools and outside agents

**Prevents:** a poisoned or silently changed outside tool steering an agent, another system's text treated as an
instruction, a write on another system nobody approved, and an outside agent holding a person's full power [04/K3, 05/SG5].

## Outside tools (this product's agents use other servers)

- Only servers in `ai/mcp-servers.yaml` are reachable, over HTTPS. Each tool there is the **reviewed copy** of its
  description and input schema; every call re-checks the live tool against it and refuses on any difference.
- A change upstream is reviewed like code: `POST /ai/mcp/servers/{server}/review`, read the diff, copy it in a commit.
- Results are external, untrusted text: data for the model, never instructions [05/SG5].
- `kind: read` runs; `kind: propose` only creates a proposal that a person approves (`outside_tool`) [04/K1].
- Credentials are per tenant, connected by an admin in person, sealed with `APP_MCP_SECRETS_KEY`; tokens stay in memory.
- A server with credentials names its `issuer`: the client secret goes only to that authorization server, never to
  one the MCP server advertises.

## This product as an MCP server (outside agents use it)

- Tokens for `/mcp` name `APP_MCP_AUDIENCE`, never the API's audience, and carry the `mcp` scope [02/Z1].
- Every caller is an agent: a token without `act` is a client acting for its `sub`. No human-only act, capabilities
  narrowed to scopes, rate limited as an agent, revocation and roles read on every call [02/Z7, 01/R3].
- Expose a capability by adding a tool in `api/mcp.py` that calls an existing use case, with its test. Never a
  write the API itself would make a proposal of.

## Change contract

| | |
|---|---|
| **Load first** | this rule, `.claude/reference/mcp-sdk.md` |
| **Run** | `make check` |
| **Same commit** | the test that proves the new tool's refusal path (changed upstream, wrong audience, another person's data) |
| **Prove** | `make mutation` still catches every MCP fault |
| **Never** | trust a tool description you didn't review; let an outside write run without a person; accept an API token at `/mcp` |
