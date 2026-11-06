---
paths:
  - "scripts/**"
  - "Makefile"
---
# Scripts and the command surface

**Prevents:** a check that scans nothing and passes, success read through a pipe, and an operator script collected as a test [10/H13, 10/H18].

- `make` is the one command surface for people, Claude and CI [10/L2]; every target says what it did.
- Scripts fail loudly: non-zero exit on any failure; no reading success through `| tail`; chain with `&&`.
- **Every check prints the size of the set it examined**, so a check that saw nothing can't pass silently [10/H18].
- Operator scripts live in `scripts/` and are never named `test_*` [06/T1].
- Scripts that touch external systems are read-only unless a human authorises a specific write [02/I7, 07/O3].
- Hooks are code: tested in both directions, documented in the hooks README, and wired exactly as documented [10/H12].

## Change contract

| | |
|---|---|
| **Load first** | `Makefile` |
| **Run** | `make check` |
| **Same commit** | the target's help text; a test proving the check can fail |
| **Prove** | the check was seen failing on a planted fault |
| **Never** | a check that can't fail; a pipe hiding an exit code |
