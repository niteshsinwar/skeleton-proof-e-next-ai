# Hooks

Hooks are code (10/H12): tested in both directions (`make harness-test`), documented here, and wired in
`.claude/settings.json` exactly as listed. `make harness-check` fails if this table, the wiring and the
scripts disagree. Protection fails closed; advisory hooks stay silent unless something is wrong (10/H11).
Event names and payloads follow the Claude Code hooks reference, verified 2026-11-04 (`.claude/reference/claude-code.md`).

| Script | Event (matcher) | Does | Blocks? |
|---|---|---|---|
| `session_start.py` | SessionStart (`startup\|resume\|clear\|compact`) | Injects tier, git state, `docs/STATE.md`, OPEN-question count and last check; records where the session started | No |
| `post_compact.py` | SessionStart (`compact`) | Prints the breadcrumb left before compaction | No |
| `drift_watch.py` | UserPromptSubmit | Warns only when `docs/STATE.md` is more than 15 commits behind HEAD | No |
| `protect.py` | PreToolUse (`Read\|Edit\|Write\|MultiEdit\|NotebookEdit\|Bash\|Grep\|Glob`) | Denies secrets, destructive git and shell, skipped hooks, production deploys, edits to accepted ADRs, rewrites of the failure log, and subagent scope breaches; unreadable input is denied | **Yes** |
| `post_edit.py` | PostToolUse (`Edit\|Write\|MultiEdit`) | Records the touched file; validates a rule's `paths:` header at once | Only on a broken rule header |
| `tool_failure.py` | PostToolUseFailure | Records the failure for the operating record | No |
| `pre_compact.py` | PreCompact | Writes the breadcrumb (plan, files, failures, last check, git state) | No |
| `stop_gate.py` | Stop | Runs `make check` when something changed; red blocks at S/E and warns at P; at E, commits without a STATE update block once | **Yes** (S/E) |
| `session_end.py` | SessionEnd | Writes the operating record to `.claude/state/sessions/` | No |

`_common.py` holds shared helpers. Runtime state (`.claude/state/`) is gitignored.
