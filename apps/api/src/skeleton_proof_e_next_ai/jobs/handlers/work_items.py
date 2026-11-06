"""EXAMPLE SLICE — reactions to work-item events. Replace with real follow-up work (notify, sync, index)."""

from __future__ import annotations

import logging
from typing import Any

from ...persistence.db import Database
from ..registry import REGISTRY

log = logging.getLogger(__name__)
KINDS = ("work_item.created", "work_item.submitted", "work_item.approved", "work_item.rejected")


async def _note(payload: dict[str, Any], db: Database) -> bool:
    log.info("work item event", extra={"fields": {"id": payload.get("id"), "sequence": payload.get("sequence")}})
    return False


for _kind in KINDS:
    REGISTRY.handler(_kind)(_note)
