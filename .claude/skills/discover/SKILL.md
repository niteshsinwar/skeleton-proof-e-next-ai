---
description: Project start (journey phase P0). Understand the problem before any design by asking the question bank, then fill docs/00-brief.md, docs/open-questions.md and this project's invariants. Use at project start or when the brief still has OPEN fields.
argument-hint: "[area to revisit, e.g. data or AI]"
---
# /discover: understand the problem before any design

**Phase P0** of the journey (11 §6). Nothing is designed or built here; everything is asked, recorded and labelled.

## Steps

1. Read what exists: `docs/00-brief.md`, `docs/open-questions.md`, `docs/decisions/`, and the client's own words in `docs/requirements/sources/`. Never ask what is already answered.
2. Work through `references/question-bank.md` in order (project start → shape → data → API → auth → frontend → AI → integrations → security → operations). Ask **one decision at a time**: situation → options with consequences → recommendation.
3. Record each answer in `docs/00-brief.md` with its label: `BRIEF`, `USER-DECISION`, `DECLARED` or `DERIVED`. Anything unanswered goes to `docs/open-questions.md` as `OPEN`.
4. Write this project's 3–8 invariants into `.claude/rules/00-invariants.md`, each with the name of the test that will prove it.
5. Confirm the tier and shape, then ask the user to accept `docs/decisions/0001-tier-and-shape.md`.
6. Ask "could plain rules or search solve enough?" before any AI design, and start `docs/architecture/decision-ownership.md` (04/P2, 04/P3).

## Exit gate (the user passes it)

- The success metric is a number, with a date and an owner.
- The cost of a wrong answer is stated, and non-goals are listed.
- Every remaining unknown is an `OPEN` row; nothing load-bearing is built on one.

**Rules in scope:** `.claude/rules/30-verify-and-report.md` (asking rule, labels) · `.claude/rules/00-invariants.md`.
