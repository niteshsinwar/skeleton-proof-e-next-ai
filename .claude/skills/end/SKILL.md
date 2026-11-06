---
description: End a session. Rewrite docs/STATE.md, add the operating record, propagate findings and commit, so the next session starts without this chat.
disable-model-invocation: true
---
# /end: leave the repo as the handoff

1. Run `make status` and `make check`; quote both results.
2. Rewrite `docs/STATE.md` (dated, under 6 KB, critical first): what is true, what is in progress, what is next, what is `OPEN`. Counts come from `make status`.
3. Add the **operating record** (10/H24) from `.claude/state/sessions/`: model and effort, permission mode and tier, MCP servers, files touched, approvals given, failures and recovery state.
4. Propagate every finding (10/H16): rule, skill or agent brief, ADR, glossary, `ops/failure-log.md`. Ask: could tomorrow's session act on this without the chat?
5. Commit with explicit paths and a Conventional Commit message that says why. If you invoked this yourself, state the commit and wait.

**Exit gate:** `make check` green, STATE dated today, nothing left only in the chat.
