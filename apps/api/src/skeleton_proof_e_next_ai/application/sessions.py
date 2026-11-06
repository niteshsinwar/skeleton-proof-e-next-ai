"""Ending a session at once (02/Z4, 03/F40): the token stops working now, not when it expires."""

from __future__ import annotations

from datetime import datetime

from ..domain.ports import AuditEvent, AuditPort, RevocationList
from ..domain.principals import Principal


async def revoke(
    revocations: RevocationList, audit: AuditPort, principal: Principal, token_sha256: str, expires_at: datetime
) -> None:
    await revocations.revoke(token_sha256, expires_at)
    await audit.append(
        AuditEvent(
            action="session.revoked",
            entity="session",
            entity_id=token_sha256[:16],  # enough to correlate, never the token itself
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=None,
            after_version=None,
        )
    )
