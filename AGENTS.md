# skeleton proof e next ai: notes for other coding agents

This is a bridge, not a second source of truth (10/L4). The working agreement is [`CLAUDE.md`](CLAUDE.md);
area rules are in `.claude/rules/` (each states the paths it governs in its `paths:` header).

- Read `docs/STATE.md` first, then the rule for the area you touch.
- Run `make check` before claiming anything is done.
- Plans and specs live in `docs/specs/<feature>/`; they are the handoff between planner and worker,
  whichever tool runs either side (10/L8).
- Never read secrets (`.env`, keys, certificates). Never deploy, push or rewrite history.
