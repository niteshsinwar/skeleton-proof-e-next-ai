"""Audit, outbox, idempotency, flags, webhook receipts, revoked tokens: the record-keeping adapters.

The audit writer appends and nothing else; its grant is insert-only (02/D6). Events go to the outbox in
the same transaction as the change and are published after commit (02/J3).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.errors import IdempotencyConflict
from ..domain.ids import new_id
from ..domain.ports import AuditEvent, PendingChange, StoredResponse
from ..telemetry import context
from . import audit_chain
from .schema import (
    audit_events,
    flags,
    idempotency_keys,
    outbox,
    pending_changes,
    revoked_tokens,
    role_grants,
    webhook_receipts,
)


def _now() -> datetime:
    return datetime.now(UTC)


class PgAudit:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def append(self, event: AuditEvent) -> None:
        values: dict[str, Any] = {
            "id": new_id(),
            "at": _now(),
            "tenant_id": event.tenant_id,
            "action": event.action,
            "entity": event.entity,
            "entity_id": event.entity_id,
            "actor": event.actor,
            "principal_kind": event.principal_kind,
            "on_behalf_of": event.on_behalf_of,
            "before_version": event.before_version,
            "after_version": event.after_version,
            "reason": event.reason,
            "correlation_id": context.correlation_id.get(),
        }
        # Link this row to the tenant's chain under the head's row lock (02/D6).
        await self.conn.execute(text(audit_chain.HEAD_INIT), {"t": event.tenant_id})
        head = (await self.conn.execute(text(audit_chain.HEAD_LOCK), {"t": event.tenant_id})).one()
        sequence = int(head.sequence) + 1
        digest = audit_chain.link(str(event.tenant_id), sequence, head.hash, values)
        values |= {"sequence": sequence, "prev_hash": head.hash, "hash": digest}
        await self.conn.execute(text(audit_chain.HEAD_MOVE), {"s": sequence, "h": digest, "t": event.tenant_id})
        await self.conn.execute(insert(audit_events).values(**values))


class PgOutbox:
    def __init__(self, conn: AsyncConnection, tenant_id: UUID) -> None:
        self.conn, self.tenant_id = conn, tenant_id

    async def publish(
        self, aggregate: str, aggregate_id: UUID, sequence: int, kind: str, payload: Mapping[str, Any]
    ) -> None:
        await self.conn.execute(
            insert(outbox).values(
                id=new_id(),
                tenant_id=self.tenant_id,
                aggregate=aggregate,
                aggregate_id=aggregate_id,
                sequence=sequence,
                kind=kind,
                payload=dict(payload),
                created_at=_now(),
            )
        )


class PgIdempotency:
    def __init__(self, conn: AsyncConnection, tenant_id: UUID) -> None:
        self.conn, self.tenant_id = conn, tenant_id

    async def lookup(self, scope: str, key: str, request_hash: str) -> StoredResponse | None:
        row = (
            await self.conn.execute(
                select(idempotency_keys).where(
                    and_(
                        idempotency_keys.c.tenant_id == self.tenant_id,
                        idempotency_keys.c.scope == scope,
                        idempotency_keys.c.key == key,
                    )
                )
            )
        ).first()
        if row is None:
            return None
        if row.request_hash != request_hash:
            raise IdempotencyConflict("This Idempotency-Key was already used with a different request.")
        return StoredResponse(status=row.status, body=row.body)

    async def remember(self, scope: str, key: str, request_hash: str, response: StoredResponse) -> None:
        await self.conn.execute(
            insert(idempotency_keys).values(
                tenant_id=self.tenant_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
                status=response.status,
                body=dict(response.body),
                created_at=_now(),
            )
        )


class PgFlags:
    """Kill switches (05/SG11): absent means on; a flag row set to false switches the feature off."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def enabled(self, key: str, tenant_id: UUID) -> bool:
        row = (
            await self.conn.execute(
                select(flags.c.enabled).where(and_(flags.c.tenant_id == tenant_id, flags.c.key == key))
            )
        ).first()
        return True if row is None else bool(row.enabled)

    async def set(self, key: str, tenant_id: UUID, enabled: bool, actor: str, reason: str) -> None:
        stmt = pg_insert(flags).values(
            tenant_id=tenant_id, key=key, enabled=enabled, updated_by=actor, updated_at=_now(), reason=reason
        )
        await self.conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[flags.c.tenant_id, flags.c.key],
                set_={"enabled": enabled, "updated_by": actor, "updated_at": _now(), "reason": reason},
            )
        )


async def record_webhook(conn: AsyncConnection, webhook_id: str, source: str) -> bool:
    """Dedupe inbound webhooks by id (02/I4). True the first time an id is seen, False on a replay."""
    stmt = pg_insert(webhook_receipts).values(webhook_id=webhook_id, source=source, received_at=_now())
    # RETURNING, not rowcount: SQLAlchemy only guarantees rowcount for UPDATE and DELETE.
    stmt = stmt.on_conflict_do_nothing(index_elements=[webhook_receipts.c.webhook_id])
    result = await conn.execute(stmt.returning(webhook_receipts.c.webhook_id))
    return result.first() is not None


class PgRevocations:
    """The revoked-token list (02/Z4). A row lives as long as its token would have; expired rows are never matched."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def revoke(self, token_sha256: str, expires_at: datetime) -> None:
        await self.conn.execute(
            pg_insert(revoked_tokens)
            .values(token_sha256=token_sha256, expires_at=expires_at, revoked_at=_now())
            .on_conflict_do_nothing(index_elements=["token_sha256"])
        )

    async def is_revoked(self, token_sha256: str, now: datetime) -> bool:
        row = await self.conn.execute(
            select(revoked_tokens.c.token_sha256).where(
                and_(revoked_tokens.c.token_sha256 == token_sha256, revoked_tokens.c.expires_at > now)
            )
        )
        return row.first() is not None


class PgGrants:
    """Role grants held by the API (02/Z5). Revoking stamps the row; nothing is deleted, so history stays (02/D6)."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def roles(self, tenant_id: UUID, subject: str) -> frozenset[str]:
        rows = await self.conn.execute(
            select(role_grants.c.role).where(
                and_(
                    role_grants.c.tenant_id == tenant_id,
                    role_grants.c.subject == subject,
                    role_grants.c.revoked_at.is_(None),
                )
            )
        )
        return frozenset(r.role for r in rows)

    async def grant(self, tenant_id: UUID, subject: str, role: str, by: str) -> bool:
        """True when the role was not already held. A revoked grant is granted again."""
        now = _now()
        values = {"tenant_id": tenant_id, "subject": subject, "role": role, "granted_by": by, "granted_at": now}
        stmt = pg_insert(role_grants).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "subject", "role"],
            set_={"granted_by": by, "granted_at": now, "revoked_by": None, "revoked_at": None},
            where=role_grants.c.revoked_at.is_not(None),
        )
        result = await self.conn.execute(stmt.returning(role_grants.c.role))
        return result.first() is not None

    async def revoke(self, tenant_id: UUID, subject: str, role: str, by: str) -> bool:
        """True when a held role was revoked now."""
        result = await self.conn.execute(
            update(role_grants)
            .where(
                and_(
                    role_grants.c.tenant_id == tenant_id,
                    role_grants.c.subject == subject,
                    role_grants.c.role == role,
                    role_grants.c.revoked_at.is_(None),
                )
            )
            .values(revoked_by=by, revoked_at=_now())
            .returning(role_grants.c.role)
        )
        return result.first() is not None


class PgChanges:
    """Pending changes for dual authorisation (02/Z6). A decision is recorded once: a decided change is final."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def propose(self, tenant_id: UUID, kind: str, payload: Mapping[str, Any], reason: str, by: str) -> UUID:
        change_id = new_id()
        await self.conn.execute(
            insert(pending_changes).values(
                id=change_id,
                tenant_id=tenant_id,
                kind=kind,
                payload=dict(payload),
                reason=reason,
                proposed_by=by,
                proposed_at=_now(),
                status="pending",
            )
        )
        return change_id

    async def get(self, tenant_id: UUID, change_id: UUID) -> PendingChange | None:
        row = (
            await self.conn.execute(
                select(pending_changes).where(
                    and_(pending_changes.c.tenant_id == tenant_id, pending_changes.c.id == change_id)
                )
            )
        ).first()
        if row is None:
            return None
        return PendingChange(row.id, row.kind, row.payload, row.reason, row.proposed_by, row.status)

    async def decide(self, tenant_id: UUID, change_id: UUID, approved: bool, by: str) -> bool:
        result = await self.conn.execute(
            update(pending_changes)
            .where(
                and_(
                    pending_changes.c.tenant_id == tenant_id,
                    pending_changes.c.id == change_id,
                    pending_changes.c.status == "pending",
                )
            )
            .values(status="approved" if approved else "rejected", decided_by=by, decided_at=_now())
            .returning(pending_changes.c.id)
        )
        return result.first() is not None
