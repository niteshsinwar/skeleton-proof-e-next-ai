# Open questions

Every unknown that matters, until it is answered. An answered question moves to the brief or an ADR,
and its row here says where (`USER-DECISION` → link). **Nothing load-bearing is built on an `OPEN` row.**

| # | Question | Blocks | Status | Answer or link |
|---|---|---|---|---|
| Q1 | Run `/discover` to fill the brief | everything | OPEN | |
| Q4 | Who owns each area? `.github/CODEOWNERS` names `@OWNER` until real people or teams replace it; the repository's rulesets then require their review (11 §4, 13/V5) | requiring reviews on the main branch | OPEN | |
| Q5 | Who is paged for each SLO alert? `ops/slo/*.yaml` names `@OWNER` until a person or rota owns each objective; `make alerts` refuses to generate rules until then (07/O15) | shipping alerts; go-live | OPEN | |

