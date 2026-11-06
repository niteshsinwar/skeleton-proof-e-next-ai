---
paths:
  - "docs/**"
  - "*.md"
---
# Docs

**Prevents:** the same fact stale in five places, a target diagram read as the running system, and a historical doc mistaken for truth [12/N9].

- **One fact, one home;** other docs link to it [12/N1]. Organise by the reader's question (`docs/README.md` is the index).
- Docs change in the same commit as the behaviour they describe. Status is counted by `make status`, never estimated.
- Mark designed vs built in every architecture doc; date anything that goes stale and give the command that re-verifies it.
- Historical docs move to a `reference/` folder with a banner naming what superseded them.
- ADRs follow `docs/decisions/0000-template.md` and are immutable once accepted (see `20-git-and-decisions.md`).
- Rules, skills and agents may only reference things that exist; `make harness-check` verifies it [10/H5].
- The doc set by tier: P has the brief, STATE, SCOPE, open questions, ADRs and specs; S adds architecture docs, what-to-trust, glossary, runbooks, SLOs and handoff; E adds the full threat model and requirement sources [12 §5].

## Change contract

| | |
|---|---|
| **Load first** | `docs/README.md` |
| **Run** | `make harness-check` |
| **Same commit** | the doc that the behaviour change made untrue |
| **Prove** | `make harness-check` passes (every referenced path exists) |
| **Never** | copy a fact into a second home; write an estimate where a count exists |
