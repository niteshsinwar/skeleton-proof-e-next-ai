#!/usr/bin/env python3
"""Verify the tier-E audit hash chain independently (02/D6): `make verify-audit`.

It imports nothing from the app (a test checks): it re-derives every hash from the stored rows with its own copy of
the specification, so a bug in the writer can't vouch for itself. It reports how many rows it examined (10/H18)
and exits 1 at the first break: a gap in the sequence, a previous hash that doesn't match, or a recomputed hash that
differs from the stored one (an edited row). It connects as APP_DATABASE_URL, which must be able to read audit.

Specification: hash = SHA-256("audit-chain/v1" NUL tenant NUL sequence NUL previous-hash NUL canonical), where
canonical is the JSON of the fields below with sorted keys, compact separators, times in UTC to the microsecond, and
every value as text or null.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import psycopg

FIELDS = (
    "id", "at", "action", "entity", "entity_id", "actor", "principal_kind",
    "on_behalf_of", "before_version", "after_version", "reason", "correlation_id",
)  # fmt: skip


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    return str(value)


def expected_hash(tenant: str, sequence: int, prev: str | None, row: dict[str, Any]) -> str:
    canonical = json.dumps({k: _text(row.get(k)) for k in FIELDS}, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(f"audit-chain/v1\x00{tenant}\x00{sequence}\x00{prev or ''}\x00".encode() + canonical).hexdigest()


def verify(conn: psycopg.Connection[Any]) -> tuple[int, list[str]]:
    columns = ", ".join(("tenant_id", "sequence", "prev_hash", "hash", *FIELDS))
    rows = conn.execute(f"SELECT {columns} FROM audit.events ORDER BY tenant_id, sequence").fetchall()  # noqa: S608
    names = ["tenant_id", "sequence", "prev_hash", "hash", *FIELDS]
    problems: list[str] = []
    tenant, last_seq, last_hash = None, 0, None
    for values in rows:
        row = dict(zip(names, values, strict=True))
        if row["tenant_id"] != tenant:
            tenant, last_seq, last_hash = row["tenant_id"], 0, None
        where = f"tenant {tenant} sequence {row['sequence']}"
        if row["sequence"] != last_seq + 1:
            problems.append(f"{where}: expected sequence {last_seq + 1} (a row is missing or out of order)")
        if row["prev_hash"] != last_hash:
            problems.append(f"{where}: previous hash does not match the row before it")
        if row["hash"] != expected_hash(str(tenant), row["sequence"], row["prev_hash"], row):
            problems.append(f"{where}: stored hash does not match its content (the row was edited)")
        last_seq, last_hash = row["sequence"], row["hash"]
    return len(rows), problems


def main() -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--database", default=os.environ.get("APP_DATABASE_URL"))
    a = p.parse_args()
    if not a.database:
        raise SystemExit("set APP_DATABASE_URL or pass --database")
    with psycopg.connect(a.database.replace("postgresql+psycopg://", "postgresql://")) as conn:
        examined, problems = verify(conn)
    print(f"verify-audit: examined {examined} audit rows")
    for problem in problems:
        print("  -", problem)
    if problems:
        print(f"verify-audit FAIL: {len(problems)} break(s) in the chain")
        return 1
    print("verify-audit: chain intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
