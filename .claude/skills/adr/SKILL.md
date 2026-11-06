---
description: Write an architecture decision record for a choice someone could reasonably question later (stack, store, shape, code-vs-model boundary, a deviation from the baseline, new infrastructure).
argument-hint: "<decision title>"
---
# /adr: record a decision

1. Take the next number in `docs/decisions/` and copy `docs/decisions/0000-template.md`.
2. Fill in context, the decision, **alternatives with why not**, consequences and a one-line defence. Record what was rejected.
3. Set **Status: Proposed**, link it from `docs/STATE.md`, and ask the user to accept it.
4. Once accepted it is immutable: only the Status and Superseded-by lines may change. A change of mind is a new ADR that supersedes it.

**Rules in scope:** `.claude/rules/20-git-and-decisions.md`.
