---
paths:
  - "apps/api/src/*/intelligence/orchestration.py"
  - "apps/api/src/*/intelligence/tools.py"
  - "apps/api/src/*/intelligence/mcp.py"
  - "apps/api/src/*/api/mcp.py"
  - "apps/api/src/*/integrations/**"
---
# Outside agents

**Prevents:** another organisation's agent steering ours, credentials passed along a chain of agents, an outside
agent's write that nobody approved, and our own agents calling each other behind the code's back [04/G3, 05/SG5].

- **An outside agent is an untrusted integration.** Its messages, artifacts and Agent Card are external data: never
  instructions, never in a system prompt, never able to drive an action on their own [05/SG5, 04/X1].
- **It reaches us through the MCP endpoint** (`api/mcp.py`): its own token audience, the agent traffic class, the
  person it acts for, nothing human-only [02/Z1, 01/R3]. A write it asks for becomes a proposal a person decides [04/K1].
- **We call one only as an integration**: an allowlisted HTTPS host through the outbound client, with a timeout and
  the retry budget [02/I1–I3]. Its card is pinned like a tool description and re-checked; a signed card's JWS is
  verified before it is trusted (A2A 8.4). What it returns is untrusted context; what it asks us to do is a proposal.
- **Our credentials never travel in-band** from agent to agent; an `auth-required` state is never authorisation in
  itself (A2A 7.6). Each hop authenticates with its own credential.
- **Our own agents never call each other** [04/G3]. Code orchestrates them (`intelligence/orchestration.py`): a
  chain, a route, a parallel fan-out, or one bounded loop. A handoff is a recorded `Handoff`, never a message.
- A2A support (an Agent Card at `/.well-known/agent-card.json`, its operations) is **not built**: add it by ADR when an
  outside agent needs it and MCP can't serve, with `.claude/reference/a2a.md` re-verified first [10/H20].

## Change contract

| | |
|---|---|
| **Load first** | this rule, `.claude/reference/a2a.md`, the MCP rule |
| **Run** | `make check` |
| **Same commit** | the test showing an outside agent's write arrives as a proposal and its text as untrusted context |
| **Prove** | the refusal path: wrong audience, another person's data, an unreviewed or changed contract |
| **Never** | an outside agent's text as an instruction; our credential handed along a chain; agent-to-agent calls between our own agents |
