---
description: Build a feature from spec to merged code (journey phases P2–P4) - research, spec, test plan, plan, red tests, green code, docs in the same commit, review.
argument-hint: "<feature name>"
---
# /feature: research → spec → test plan → red → green → docs

1. **Intake:** defect or new requirement? Which areas does it touch? Extend something existing before creating anything. Propose the approach in 2–3 lines and wait.
2. **Research** (`docs/specs/<feature>/research.md`): read the installed versions' docs for anything external (`.claude/rules/40-research.md`).
3. **Spec** (`spec.md`): requirements labelled `BRIEF` / `USER-DECISION` / `DECLARED` / `DERIVED` / `OPEN`; acceptance criteria as Given-When-Then. The `spec-reviewer` agent reviews it.
4. **Test plan** (`test-plan.md`): behaviours, layer, input, hard-coded expected output, at least one error and one edge case per happy path (06/T2).
5. **Plan** (`plan.md`): vertical slices, each with a "complete only when" line.
6. **Red:** the `test-author` agent writes the tests from the spec without seeing the implementation; run them and see them fail for the stated reason.
7. **Green:** implement the smallest change that passes; never edit the tests to make them pass.
8. **Same commit:** docs that became untrue, STATE if needed, eval cases for AI behaviour. Then `/review`.

Specialised paths: `/endpoint` · `/screen` · `/data-model` · `/integration` · `/ai-step`.

**Exit gate:** `make check` green; review findings at Critical and High resolved.
