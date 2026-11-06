---
description: Report counted status (decisions, open questions, scope, failures, rules, tests) and where docs/STATE.md disagrees with it. Never estimate a percentage.
---
# /status: counted, never estimated

1. Run `make status`.
2. Compare it with `docs/STATE.md`; list every number that disagrees and which one is true (order of trust: the count wins).
3. Report the `OPEN` questions that block the next scope row.

**Output:** the `make status` table, the disagreements, the blockers. No percentages (12/N9).
