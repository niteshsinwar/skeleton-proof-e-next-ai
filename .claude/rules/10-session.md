# The session loop (always loaded)

**Prevents:** work the next session redoes, a plan lost to compaction, a finding that reaches nobody [10/H14–H16].

- **Start:** the session-start hook injects `docs/STATE.md`, git state and the last check result. Read the rule for the area before editing.
- **Plan to disk** before building anything that touches more than about 3–5 files: `docs/specs/<feature>/plan.md` [10/H15, 10/H19].
- **Knowledge lives in the repo:** `docs/STATE.md` (dated, under 6 KB, critical first), `docs/decisions/`, `docs/open-questions.md`, `docs/SCOPE.md` (counted rows) and `ops/failure-log.md` [10/H14]. Any memory outside the repo is a convenience copy; promote anything durable into the repo.
- **A finding is filed only when propagated** to STATE, the rule, the skill or agent brief, an ADR or the glossary. Test: could tomorrow's session act on it without this chat? [10/H16]
- **End with `/end`:** rewrite STATE, write the operating record (model, effort, permissions, tier, MCP servers, files touched, approvals, failures, recovery state) and commit [10/H24].
- **At tier E**, `/end` before stopping is required (the Stop gate blocks) [10 §4].

## Change contract

| | |
|---|---|
| **Load first** | `docs/STATE.md` |
| **Run** | `make status` |
| **Same commit** | `docs/STATE.md` with the change that made it untrue |
| **Prove** | STATE quotes counts from `make status`, not estimates |
| **Never** | leave a decision, failure or open question only in the chat |
