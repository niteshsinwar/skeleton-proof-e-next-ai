---
paths:
  - "apps/api/src/*/intelligence/**"
  - "ai/**"
---
# Product AI

**Prevents:** "plausible, well-formatted and wrong" reaching users, a model deciding what code must own, safety checks that fail open, and runaway agents [04].

- Ask first whether plain rules or search solve enough; then the delegation test (reversible? cost? who answers for it?) [04/P1, 04/P2].
- Two AIs, two harnesses: `.claude/` builds the product, `ai/` is the product's governed AI; separate budgets, and nothing crosses without evidence [10/H8].
- A decision-ownership table (code / model / human) in `docs/architecture/decision-ownership.md`, written before the code and enforced in code [04/P3]. Security, permission, money and state transitions are code-owned; floors are one-directional [04/P4].
- **Fail closed:** provider down or malformed output → block, escalate or abstain [04/P5]. **The model reports facts; code decides:** cited ids with verbatim spans, verified by exact substring; reject, never repair [04/P6]. Known limitations are designed for [04/P7].
- The least-autonomous pattern that works; one agent before many; multi-agent only when an eval shows the gain [04/G1, 04/G2, 04/IL2]. The orchestrator sequences everything; agents never call agents [04/G3]. Independent flows share no mutable state [04/G4]. Budgets and loop detection on every run [04/G5]. Approvals gate writes [04/G7].
- One tool registry; read tools execute, write tools return proposals; every tool call validated, timed out and audited; MCP allowlisted; generated code only in a sandbox [04/K1–K4].
- An agent is a folder of versioned files referencing its eval set; no prompt text at call sites [04/Q1, 12/NL8]. Structured output is schema-constrained **and** validated in code [04/Q4, 04/IL3]. Abstention is a first-class output [04/Q5].
- A context ledger for every call; stable content first; long runs managed deliberately [04/X1–X3]. Three records per attempt [04/X6]. Long-term memory only from human-confirmed outcomes [04/X7, 04/IL4].
- Models chosen by tier and evals; every model change re-runs the evals; cost per attempt recorded; data sent to a provider minimised [04/M1–M4]. Oversight chosen by consequence; gates leave evidence; fairness by matched pairs; users told it's AI [04/H1–H4].
- Orchestration: the plain primitives first (`intelligence/orchestration.py`: chain, route, parallel, a bounded agent
  loop); LangGraph for durable human-in-the-loop graphs (`intelligence/graphs/`) [13/SK5].

## Where things live

| Need | Home |
|---|---|
| Which model and provider a kind of call uses | `ai/models.yaml` (routes → models → providers) [01/C5, 13/V7] |
| The one module that calls models | `intelligence/gateway.py`; adapters in `intelligence/providers/` |
| A step's contract and prompt | `ai/agents/<agent>/v<N>.yaml`, pinned in `ai/agents/pins.json` [04/Q1] |
| Registering a step | `intelligence/project_steps.py` [02/B4] |
| Calling a step from a use case | `application/ai_runs.py` (admit, run, record) [02/J1] |
| Tools and proposals | `intelligence/tools.py`, `application/proposals.py`, `api/proposal_kinds.py` [04/K1] |

## Change contract

| | |
|---|---|
| **Load first** | `docs/architecture/decision-ownership.md`, the agent file, its eval set |
| **Run** | `make check` and `make eval` |
| **Same commit** | eval cases (incl. adversarial) for new behaviour; a new agent version for any prompt change |
| **Prove** | the real-model eval ran at least 3 times and was recorded [06/E4] |
| **Never** | a model deciding security, permission, money or a state transition; a mocked model proving behaviour [06/T4] |
