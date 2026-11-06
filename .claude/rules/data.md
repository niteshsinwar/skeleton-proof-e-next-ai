---
paths:
  - "apps/api/src/*/domain/**"
  - "docs/architecture/data-model.md"
---
# Data model

**Prevents:** string timestamps, missing foreign keys, PII nobody classified, and state that can be retrieved stale [02 §3].

- **Column checklist:** plural `snake_case` tables, typed ids, UUIDv7 keys, `created_at`/`updated_at` as `timestamptz`, `created_by`, `version`; NOT NULL by default; CHECKs for ranges and enums; FKs with an explicit `ON DELETE`; unique business keys; units in names; **a data class per column**; JSONB only for schemaless payloads with a schema version [02/D4, 05/SG7].
- A deletion policy per entity; erasure follows a data map across every derived store [02/D8].
- Configuration that changes behaviour is versioned, effective-dated data, never edited once pinned [02/D9].
- Deliberate absences are listed and tested (no soft delete on audit, no protected attributes) [02/D10].
- Generated and synthetic data come from one deterministic command and are labelled as synthetic in the data; released datasets are immutable [02/D16].
- The store follows the data's shape; never everything in a vector store [02/D11]. **Live state is queried, never retrieved** [02/D12].
- Workflow state is named states entered by named commands; an illegal command leaves no partial state [02/D13].
- Constructors refuse illegal states; value objects are immutable [02/B6]. Money in minor units with a currency [02/B9].

## Change contract

| | |
|---|---|
| **Load first** | `docs/architecture/data-model.md` |
| **Run** | `make check` |
| **Same commit** | the data-model doc (class, deletion policy, absences); migration; constructor tests |
| **Prove** | an illegal state is refused by a test |
| **Never** | a column with no data class; a string timestamp; a stored protected attribute |
