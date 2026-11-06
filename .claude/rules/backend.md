---
paths:
  - "apps/api/src/**"
  - "apps/api/config/**"
---
# Backend structure

**Prevents:** god modules, layers importing the wrong way, invariants skipped on load, and failures that look like success [02 §1].

| Classic name | Here | Holds | Never holds |
|---|---|---|---|
| Controller | `api/routers/<resource>.py` | parse, authorise, call **one** use case, shape the response | business rules, SQL, commits |
| Service | `application/<feature>.py` | use cases (verbs); owns the transaction | domain decisions, HTTP |
| Domain | `domain/` | entities and value objects (nouns), invariants, `ports.py` | imports from outer layers, I/O |
| Repository | `persistence/` | load and save aggregates **through constructors** | commits, business rules |
| Adapter | `integrations/`, `intelligence/`, `retrieval/` | one vendor or engine behind a port | domain decisions; state writes (AI) |

- Dependencies point inward, enforced by the AST layering test, which reports how many modules it examined [02/B1].
- Ports are `typing.Protocol`, shaped by what the domain needs; least privilege through the interface [02/B3].
- One registry per extensible thing; an unregistered module on disk fails a test [02/B4].
- A dependency is admitted, not added: the reason, the alternative considered, maintenance health and licence, recorded in the PR (and an ADR from tier S) [13/V2, 03/F51].
- What varies is configuration: business config in `apps/api/config/` (versioned, effective-dated, strict loader rejecting unknown keys); process settings in `src/<pkg>/config/` [02/B5, 02/D9].
- Constructors refuse illegal states; domain objects are never ORM instances [02/B6, 02/BL2].
- Errors are explicit: no bare `except`, no fallback that looks like success, degradation recorded in the result [02/B7].
- One module owns model calls, one owns audit writes, one owns each external system; correlation travels in `contextvars` [02/B8].
- Apps never import each other; they share only `packages/contracts` (schemas), never business code [12/N3]. Names: Python modules `snake_case`, TS files `kebab-case`, a folder only when two or more files share a theme [12/N7].
- State complexity where n can grow; money in minor units; time as UTC `timestamptz`; waiting time is a union of intervals [02/B9].
- `async def` end to end; no blocking call inside an async path (ruff `ASYNC` rules) [13/SK2].
- ruff and `mypy --strict` gate every commit [02/B10].

## Change contract

| | |
|---|---|
| **Load first** | the package's module, its tests, this rule's map |
| **Run** | `make check` |
| **Same commit** | tests for the behaviour; this map if a package was added [02/B2] |
| **Prove** | the layering test's examined-module count went up when a module was added |
| **Never** | business logic in a router; an ORM object in the domain; a bare `except` |
