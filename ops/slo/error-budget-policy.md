# Error-budget policy

Each SLO leaves a budget of failure: 99.5% availability over 30 days allows about 3.6 hours of errors. The budget is
spent on releases, experiments and incidents; this page says what happens as it runs out (07/O13). Agreed by the
product owner and the engineering lead; changed only by a decision record.

| Budget left in the window | What changes |
|---|---|
| More than 50% | Normal releases. |
| 50% to 25% | Each release states its risk in the pull request; risky changes wait for a canary on staging first. |
| Less than 25% | Only fixes and reliability work ship; feature releases wait. The owner reviews the causes weekly. |
| Spent | Feature releases stop until the SLO is back within target for 7 days or a decision record accepts the risk. The next sprint's first item is the top cause of spent budget. |

Rules that always apply:

- A single incident that spends more than 20% of a budget gets a written review and a failure-log entry
  (`ops/failure-log.md`), whatever the remaining budget.
- An SLO missed three windows in a row is either fixed or its target is lowered by a decision record; a target nobody
  defends is not a target.
- Security fixes and data-loss fixes ship regardless of the budget.
- An alert nobody acted on is deleted or fixed in the same week (07/O15).
