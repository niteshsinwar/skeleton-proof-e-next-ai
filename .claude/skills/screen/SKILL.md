---
description: Build or change a screen - persona and journey first, generated API client, tokens only, every state (empty, error, loading), performance budget, accessibility and the six-lens review.
argument-hint: "<screen or journey>"
---
# /screen: a journey step, not a page of widgets

1. Name the persona and the journey step; read `docs/design/00-design-language.md`.
2. Data: the generated client and one module per resource; server reads by default, TanStack Query only for interactive data; declare each query's freshness; push vs poll chosen by change rate.
3. Build from owned primitives with tokens only; every data component has empty, error and loading states; on-screen words come from the labels module.
4. AI output (if any) shows provenance, what it couldn't verify, and abstention as itself.
5. Tests: unit tests for `lib/` logic; an e2e journey on the built artefact with axe; Core Web Vitals budget.
6. Record a new pattern in `docs/design/ui-decisions.md`; run `/review` (six lenses).

**Rules in scope:** `.claude/rules/frontend.md`. **Exit gate:** `make check` green; the journey passes on the built artefact.
