"""The tier-E audit hash chain (02/D6): every audit row is linked to the one before it, per tenant.

hash = SHA-256( "audit-chain/v1" NUL tenant NUL sequence NUL previous-hash NUL canonical-event )

The chain head row is locked in the writing transaction, so two writers can't fork it; the table enforces one row
per (tenant, sequence) and a null previous hash only at sequence 1. scripts/verify_audit_chain.py re-derives every
hash with its own code and imports nothing from here. Say "tamper-evident", never "immutable" (02/D6).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

DOMAIN = "audit-chain/v1"
FIELDS = (
    "id",
    "at",
    "action",
    "entity",
    "entity_id",
    "actor",
    "principal_kind",
    "on_behalf_of",
    "before_version",
    "after_version",
    "reason",
    "correlation_id",
)

HEAD_INIT = "INSERT INTO audit.chain_heads (tenant_id, sequence, hash) VALUES (:t, 0, NULL) ON CONFLICT DO NOTHING"
HEAD_LOCK = "SELECT sequence, hash FROM audit.chain_heads WHERE tenant_id = :t FOR UPDATE"
HEAD_MOVE = "UPDATE audit.chain_heads SET sequence = :s, hash = :h WHERE tenant_id = :t"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    return str(value)


def canonical(event: Mapping[str, Any]) -> bytes:
    """Sorted keys, compact separators, UTF-8; times in UTC to the microsecond; every value as text or null."""
    return json.dumps({k: _text(event.get(k)) for k in FIELDS}, sort_keys=True, separators=(",", ":")).encode()


def link(tenant_id: str, sequence: int, prev_hash: str | None, event: Mapping[str, Any]) -> str:
    head = f"{DOMAIN}\x00{tenant_id}\x00{sequence}\x00{prev_hash or ''}\x00".encode()
    return hashlib.sha256(head + canonical(event)).hexdigest()
