# Git and decisions (always loaded)

**Prevents:** bulk commits that hide decisions, history rewritten under people, and choices nobody can later explain [10/H13, 11 §4].

## Git

- **Trunk-based:** `main` is always releasable; branches live under a day; environments promote the built artefact, never a branch [11/GL1].
- **One decision per commit.** Stage paths explicitly (`git add <paths>`), never everything at once. The pre-commit granularity guard limits files and top-level areas per commit [10/H13].
- **Conventional Commits** with a body that says *why* (checked by the commit-msg hook). Merge with rebase or a merge commit, never squash multi-decision work [11/GL2].
- **Never** force-push, rewrite `main`, skip hooks, or read success through a pipe. Chain with `&&`. If history must change, publish an old → new map.
- A secret that reached git is **rotated**, not just removed [05/SG12].

## Decisions (ADRs)

- An ADR for every choice someone could reasonably question later: tier and shape, stack, data store, the code-vs-model boundary (recorded both ways), any deviation from the baseline, any infrastructure added [10 §4].
- At tier E an ADR is also required for: a new dependency, service or store, and any boundary or invariant change [10 §4].
- Template: `docs/decisions/0000-template.md`. Numbered and **immutable once accepted**; only the Status and Superseded-by lines may change (the protect hook enforces it). A change of mind is a new ADR.
- Record what was rejected and why; a rejected option is as valuable as an adopted one.

## Change contract

| | |
|---|---|
| **Load first** | `docs/decisions/` |
| **Run** | `make check` |
| **Same commit** | the ADR with the change it justifies; STATE if it changes what is true |
| **Prove** | the commit touches one decision; its message says why |
| **Never** | edit an accepted ADR's body, `git add -A`, force-push, `--no-verify` |
