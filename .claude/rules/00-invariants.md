# Invariants and non-negotiables (always loaded)

**Prevents:** the failures every one of our projects hit at least once (baseline README and 99).

## This project's invariants

3–8 things that must never happen, each enforced by a named test that fails if it does [06/T3].
Fill them in during `/discover`. Removing or weakening one needs an ADR.

| # | Must never happen | Test that fails if it does |
|---|---|---|
| I1 | `OPEN`: set during `/discover` | — |

## Universal non-negotiables

1. **Discovery before design:** the user, the job, the success number, the cost of a wrong answer, the constraints [11 §6 P0].
2. **The simplest shape that works.** A service, store or agent is added only for a measured gap, by ADR [01/S2, 01/S3, 01/R10].
3. **Dependencies point inward.** The domain imports nothing; databases, models and vendors are adapters behind ports [02/B1, 02/B3].
4. **The API is stateless**, and every kind of state has one named home [01/T1].
5. **Guarantees live in code:** types, constraints, failing tests, hooks. A sentence in a doc is guidance, not enforcement [06/T3, 10/H4].
6. **Fail closed.** No silent fallbacks; an unknown configuration key raises [02/B5, 02/B7, 04/P5].
7. **Declare who owns each decision** (code, model or human) and enforce it; a deterministic floor only raises risk [04/P3, 04/P4].
8. **Model output is untrusted input:** schema-validated at the boundary and never executed [04/Q4, 02/A16].
9. **Reads run freely; consequential writes become proposals**, each with an idempotency key and an audit event [04/K1, 02/A5].
10. **Secrets never enter git, images, logs or chat;** an exposed secret is rotated [05/SG12, 02/Z13].
11. **Every bug becomes a test and every AI failure an eval case;** a gate that cannot fail is fixed or deleted [06/T9, 06/E3].
12. **Never present a fake as real.** Label estimates as estimates and unbuilt features as unbuilt.
13. **Docs change in the same commit as behaviour;** status comes from a count, never an estimate [12/N9].
14. **Production is read-only to tools and agents;** deploys are human actions and the environment is always explicit [07/O3].
15. **Observe from day one:** a correlation id, JSON logs without PII, the build SHA on the health endpoint, real model cost [07/O7, 02/A12].

## Change contract

| | |
|---|---|
| **Load first** | `docs/00-brief.md`, `docs/decisions/` |
| **Run** | `make check` |
| **Same commit** | the invariant's test; `docs/STATE.md` when what is true changes |
| **Prove** | the invariant's test was seen failing before the code that satisfies it [06/T2] |
| **Never** | weaken, skip or delete an invariant test without an ADR |
