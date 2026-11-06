---
description: Add or change an entity or table - lifecycle questions, the column checklist, data class, deletion policy, zero-downtime migration, constructor, grant and row-level security tests.
argument-hint: "<entity>"
---
# /data-model: design the table before writing it

1. Ask what isn't known: lifecycle, what must never be deleted, retention per data class, soft vs hard delete, history needs, money, units and time zones, the tenancy boundary, who may see which rows.
2. Apply the column checklist (UUIDv7 keys, `timestamptz`, `version`, NOT NULL by default, CHECKs, FKs with `ON DELETE`, unique business keys, units in names, a data class per column).
3. Write the entity's row in `docs/architecture/data-model.md`: data classes, deletion policy, deliberate absences.
4. Migration: expand → backfill in batches → contract; `lock_timeout`; indexes `CONCURRENTLY`; tested up and down.
5. Domain constructor refuses illegal states; the repository rebuilds through it; grant tests as the app role; RLS tests across tenants.

**Rules in scope:** `.claude/rules/data.md` · `.claude/rules/persistence.md`. **Exit gate:** `make check` green; the migration went down and up on a scratch DB.
