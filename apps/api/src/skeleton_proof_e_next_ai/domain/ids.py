"""UUIDv7 everywhere: sortable, non-enumerable across tenants (02/BL4)."""

from __future__ import annotations

import uuid


def new_id() -> uuid.UUID:
    return uuid.uuid7()
