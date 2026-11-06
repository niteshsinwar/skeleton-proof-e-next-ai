"""Standard Webhooks verification (02/I4, 02/BL8, W25).

HMAC-SHA256 over "{id}.{timestamp}.{raw body}", constant-time comparison, a 5-minute timestamp window,
and several signatures accepted during key rotation. Dedupe by id is persistence.records.record_webhook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping

TOLERANCE_SECONDS = 300


class InvalidWebhook(Exception):
    pass


def _key(secret: str) -> bytes:
    return base64.b64decode(secret.removeprefix("whsec_"))


def sign(secret: str, webhook_id: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(_key(secret), f"{webhook_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def verify(secrets: list[str], headers: Mapping[str, str], body: bytes, now: int) -> str:
    """Return the webhook id if valid; raise InvalidWebhook otherwise. `body` must be the raw bytes."""
    try:
        webhook_id = headers["webhook-id"]
        timestamp = int(headers["webhook-timestamp"])
        offered = headers["webhook-signature"].split()
    except (KeyError, ValueError) as exc:
        raise InvalidWebhook("missing or malformed webhook headers") from exc
    if abs(now - timestamp) > TOLERANCE_SECONDS:
        raise InvalidWebhook("timestamp outside the allowed window")
    for secret in secrets:
        expected = sign(secret, webhook_id, timestamp, body)
        if any(hmac.compare_digest(expected, sig) for sig in offered):
            return webhook_id
    raise InvalidWebhook("no valid signature")
