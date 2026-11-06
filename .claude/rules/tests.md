---
paths:
  - "**/tests/**"
  - "tests/**"
  - "scripts/mutation_check.py"
---
# Tests

**Prevents:** a green suite over a broken system, tests that pass on an empty fixture, and a fix "confirmed" by one lucky run [06 §1].

- **Lanes by cost**, gated by marker and env var; plain `pytest` is free and offline: unit · invariant · integration on real Postgres · contract · e2e on the built artefact · evals · live sandbox · load · stress · post-deploy smoke [06/T1].
- Tests live with what they test (`apps/<app>/tests/`); the root `tests/` holds only system lanes (image, load, post-deploy smoke); operator scripts are never named `test_*` [12/N5].
- **Red first:** a test plan from the spec with hard-coded expected values; tests written without sight of the implementation (the `test-author` agent can't read source); implementation never edits tests; one error and one edge case per happy path [06/T2].
- Every prohibition is a named failing test; critical invariants have independent tests [06/T3].
- Never mock the model to prove behaviour; never fake the database; prefer a live sandbox; inject time, randomness and ids [06/T4].
- Cases come from technique (partitions, boundaries, decision tables, state transitions) plus property-based tests [06/T5].
- **Honest fixtures:** read the fixture first; pair every negative assertion with a positive one; no assertion that accepts either answer; include patterns cover every test file [06/T6].
- Mutation proves catch-power on critical paths; the proof is the failure message; revert by edit, never `git checkout` [06/T7, 06/EL4].
- Defects: classify defect vs new requirement; every fix ships with the test that would have caught it [06/T9]. Suites never share a database; no hard-coded dates [06/T10].

## Change contract

| | |
|---|---|
| **Load first** | the spec's `test-plan.md` and the fixture |
| **Run** | `make test` |
| **Same commit** | the failing-first test with the fix |
| **Prove** | the test was seen failing for the stated reason before the fix |
| **Never** | edit a test to make implementation pass; a mocked model as behavioural proof; a test DB shared with dev |
