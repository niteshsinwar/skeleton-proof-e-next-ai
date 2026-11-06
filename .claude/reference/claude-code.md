# Claude Code facts the harness relies on

Verified 2026-11-04 against the official docs (code.claude.com/docs/en: hooks, settings, permissions,
memory, skills, sub-agents). Label: READ, with long pages partly summarised by the fetch tool; re-verify by 2026-11-25.

- **Hook events used:** SessionStart (matchers `startup`, `resume`, `clear`, `compact`), UserPromptSubmit,
  PreToolUse, PostToolUse, PostToolUseFailure, PreCompact, Stop, SessionEnd. PostCompact also exists.
- **Hook I/O:** JSON on stdin (`session_id`, `cwd`, `hook_event_name`, `permission_mode`; tool events add
  `tool_name` and `tool_input`; subagent calls add `agent_type`; Stop adds `stop_hook_active`).
  PreToolUse denies with `hookSpecificOutput.permissionDecision = "deny"` plus a reason; Stop and PostToolUse
  block with top-level `decision: "block"` and `reason`. SessionStart and UserPromptSubmit stdout reaches Claude.
  `CLAUDE_PROJECT_DIR` is the project root. Default timeout 600 s (30 s for UserPromptSubmit).
- **Permissions:** `allow`, `ask`, `deny` arrays; deny wins. Read rules use gitignore patterns (`Read(.env)`
  matches at any depth). Bash rules use the space-star form (`Bash(git push --force *)`).
- **Rules:** `.claude/rules/*.md` with a `paths:` list of globs load when matching files are read or edited;
  rules without `paths:` load at launch. **Invalid YAML makes a rule load as if it had no paths.**
  CLAUDE.md: keep it small (docs: under 200 lines; this harness: 120).
- **Skills:** `.claude/skills/<name>/SKILL.md`; `description` recommended (truncated at 1,536 characters);
  optional `disable-model-invocation`, `argument-hint`, `allowed-tools`, `context: fork`. Keep under 500 lines.
- **Subagents:** `.claude/agents/<name>.md` with `name` and `description`; `tools` (inherited when omitted)
  and `disallowedTools`.
