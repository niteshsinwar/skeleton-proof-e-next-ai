## What and why

<!-- One decision per commit (10/H13). Link the spec, issue or ADR. -->

## Type of change

- [ ] Defect fix (ships with the test that would have caught it, 06/T9)
- [ ] New requirement (a spec under `docs/specs/`)
- [ ] Schema or migration (expand → migrate → contract; down migration tested, 02/D2–D3)
- [ ] Configuration (business config is versioned data, 02/B5)
- [ ] Prompt, model or AI step (the evals re-run and recorded, 04/M2, 06/E8)
- [ ] Dependency (admitted: reason, alternative, health, licence, 13/V2)
- [ ] Workflow or harness change (CODEOWNERS review, 13/V5)

## What could have failed, and the evidence it didn't

<!-- Not a pass count: a check that could have failed (06). Name the tests, the planted fault, the eval run. -->

## Checklist

- [ ] `make check` green on this commit
- [ ] Docs changed in the same commit as the behaviour (12/N9)
- [ ] For auth, data, uploads, tools or AI: the security checklist in 05 §4 is answered
- [ ] Screenshots for screens; `labels.ts` for any new on-screen word (03/F16)
