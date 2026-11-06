"""Handle verified webhook deliveries in the background (02/I4). One kind per source event is the usual next step:
parse the body against the source's published schema (02/I6), resolve the tenant from it, then act idempotently.
"""

from __future__ import annotations

import logging
from typing import Any

from ...persistence.db import Database
from ..registry import REGISTRY

log = logging.getLogger(__name__)
KINDS = ("webhook.received",)


@REGISTRY.handler("webhook.received")
async def received(payload: dict[str, Any], db: Database) -> bool:
    log.info("webhook received", extra={"fields": {"source": payload.get("source"), "id": payload.get("id")}})
    return False
