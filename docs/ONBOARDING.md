# Onboarding: skeleton proof e next ai

1. Read [`STATE.md`](STATE.md), then [`00-brief.md`](00-brief.md).
2. Run `make setup` and `make check`; both must succeed before you change anything.
3. Read [`../CLAUDE.md`](../CLAUDE.md) for where things go and how work is done here.
4. Area rules live in `.claude/rules/` and load automatically for Claude when matching files are touched; people should read the rule for the area they work in.
5. Decisions and their reasons: [`decisions/`](decisions/). Failures and what they taught us: `../ops/failure-log.md`.
6. Status is counted: `make status`. Don't quote a number that isn't from it.
