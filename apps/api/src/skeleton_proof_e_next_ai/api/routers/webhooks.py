"""Inbound webhooks (02/I4): verify, dedupe, queue, acknowledge.

The signature over the raw body is the authentication, so there is no session. A replayed or duplicated delivery is
acknowledged and does nothing; the work runs in the background, keyed by the webhook id, so it happens once.
Which tenant an event belongs to is decided by its handler from the payload, never from the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...integrations.webhooks.verify import InvalidWebhook, verify
from ...jobs import queue
from ...persistence.records import record_webhook
from ...security.rate_limit import WEBHOOK_LIMIT
from ..deps import now, state
from ..errors import ProblemError

router = APIRouter(tags=["webhooks"])
KIND = "webhook.received"


@router.post("/webhooks/{source}", status_code=202)
async def receive_webhook(source: str, request: Request) -> JSONResponse:
    st = state(request)
    secrets = st.settings.webhook_secrets.get(source)
    if not secrets:
        raise ProblemError(404, "not-found", "No such webhook.")
    try:
        decision = await st.limiter.check(f"webhook:{source}", WEBHOOK_LIMIT, now())
    except Exception as exc:  # the limiter's store failing refuses rather than lets everything in (01/R2)
        raise ProblemError(503, "rate-limiter-unavailable", "Try again shortly.", {"Retry-After": "5"}) from exc
    if not decision.allowed:
        retry = {"Retry-After": str(decision.retry_after_seconds)}
        raise ProblemError(429, "rate-limited", "Too many deliveries.", retry)
    body = await request.body()
    if len(body) > st.settings.webhook_max_bytes:
        raise ProblemError(413, "payload-too-large", "The delivery is too large.")
    try:
        webhook_id = verify(secrets, request.headers, body, int(datetime.now(UTC).timestamp()))
    except InvalidWebhook as exc:
        raise ProblemError(401, "invalid-signature", "The delivery could not be verified.") from exc
    async with st.db.transaction(tenant_id=None, actor=f"webhook:{source}") as conn:
        if not await record_webhook(conn, webhook_id, source):
            return JSONResponse({"id": webhook_id, "duplicate": True}, status_code=200)
        await queue.enqueue(
            conn,
            KIND,
            {"source": source, "id": webhook_id, "body": body.decode("utf-8", "replace")},
            idempotency_key=f"webhook:{source}:{webhook_id}",
        )
    return JSONResponse({"id": webhook_id, "duplicate": False}, status_code=202)
