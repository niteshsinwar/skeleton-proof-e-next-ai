---
description: Record a failure (loud or quiet) in ops/failure-log.md and route it to the hardening that stops it recurring. Use for any bug, bad output, broken gate or harness miss.
argument-hint: "<what happened>"
---
# /failure-log: every failure ends in a hardening (10/H17)

1. Append (never edit old entries; the log is append-only) a new `## F-NNN` entry: date, loud or quiet, what happened, how it was detected, root cause.
2. Choose its home with the routing table (10/H23):

| The failure was… | Its hardening is… |
|---|---|
| a dangerous action | a deny rule or a hook |
| a repeatable workflow done wrong | a skill |
| an area convention broken | a path rule |
| a fact about the project | `docs/STATE.md` or an ADR |
| a product behaviour | a test or an eval case |

3. The **second** occurrence of the same failure must become a rule, hook or test, linked from the entry.
4. Commit the entry with its hardening.
