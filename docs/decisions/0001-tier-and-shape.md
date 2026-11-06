# ADR-0001: Tier, shape and stack

**Status:** Proposed
**Superseded by:** —
**Date:** set when accepted · **Decider:** the project owner

## Context

The project was rendered from the engineering baseline skeleton with these answers: tier **E**,
web UI **next**, AI **yes**, tenancy **multi**. `/discover` confirms or changes them.

## Decision

- Tier E (01/S1): when in doubt, the higher tier for data and security, the lower for infrastructure.
- Shape: a modular monolith, one deployable, one Postgres database (01/S2). A separate service only for a named reason, by its own ADR (01/S3).
- Stack (13): FastAPI, async end to end, SQLAlchemy Core with psycopg 3, Alembic, PostgreSQL 18; Next.js 16; the provider's official SDK behind our LLM port.
- Tenancy: shared schema + `tenant_id` + row-level security (02/Z9).

## Alternatives considered

| Option | Why not |
|---|---|
| Microservices from day one | No named reason yet (01/S3); every split costs operations and consistency |
| `OPEN` | Filled in during `/discover` |

## Consequences

The baseline's rules for this tier apply (`.claude/rules/`). Moving up a tier later is an extension, not a rewrite.

## One-line defence

The simplest shape that meets today's needs, with the tier's guarantees enforced in code.
