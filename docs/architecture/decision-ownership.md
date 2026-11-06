# Decision ownership: code, model, human

> Each row names the code and test that enforce it; a row without them is designed, not built.

Written before the code and enforced in code; no hidden layer may overrule the declared owner (04/P3).
Security, permission, money and state transitions are always code-owned (04/P4).

| Decision | Owner (code / model / human) | Enforced by | What the model may not do |
|---|---|---|---|
| `work_item_brief` (EXAMPLE): what the approver should know about a work item | model drafts the points; **code** checks every quote against the record and turns an unsupported brief into an abstention; a **human** decides the item | `intelligence/work_item_brief.py` (`needs_a_point`), the citation verifier, `test_ai_example.py` | recommend approve or reject; state anything the record doesn't say; act on instructions inside the record |
