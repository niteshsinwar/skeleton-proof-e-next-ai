"""Kill switches as an audited control plane (05/SG11). Only humans with flags.set may flip them.

At tier E a switch is sensitive configuration under dual authorisation (02/Z6): one admin proposes, a different
admin approves, and only then does it change. Both acts are audited."""

from __future__ import annotations

from uuid import UUID

from ..domain.errors import Forbidden, InvariantViolated, NotFound
from ..domain.ports import AuditEvent, AuditPort, ChangesPort, FlagPort
from ..domain.principals import Capability, Principal


async def set_flag(
    flags: FlagPort, audit: AuditPort, principal: Principal, key: str, enabled: bool, reason: str
) -> None:
    principal.require(Capability.FLAGS_SET)
    if not reason.strip():
        raise InvariantViolated("Switching a flag needs a reason.")
    await flags.set(key, principal.tenant_id, enabled, principal.subject, reason)
    await audit.append(
        AuditEvent(
            action="flag.set",
            entity="flag",
            entity_id=key,
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=None,
            after_version=None,
            reason=f"{'on' if enabled else 'off'}: {reason}",
        )
    )


KIND = "flag.set"


def _event(principal: Principal, action: str, entity_id: str, reason: str) -> AuditEvent:
    return AuditEvent(
        action=action,
        entity="pending_change",
        entity_id=entity_id,
        actor=principal.subject,
        principal_kind=principal.kind.value,
        on_behalf_of=principal.on_behalf_of,
        tenant_id=principal.tenant_id,
        before_version=None,
        after_version=None,
        reason=reason,
    )


async def propose_flag(
    changes: ChangesPort, audit: AuditPort, principal: Principal, key: str, enabled: bool, reason: str
) -> UUID:
    principal.require(Capability.FLAGS_SET)
    if not reason.strip():
        raise InvariantViolated("Switching a flag needs a reason.")
    payload = {"key": key, "enabled": enabled}
    change_id = await changes.propose(principal.tenant_id, KIND, payload, reason, principal.subject)
    summary = f"{key} {'on' if enabled else 'off'}: {reason}"
    await audit.append(_event(principal, "change.proposed", str(change_id), summary))
    return change_id


async def decide_change(
    changes: ChangesPort,
    flags: FlagPort,
    audit: AuditPort,
    principal: Principal,
    change_id: UUID,
    approve: bool,
    reason: str,
) -> None:
    principal.require(Capability.FLAGS_SET)
    change = await changes.get(principal.tenant_id, change_id)
    if change is None or change.kind != KIND:
        raise NotFound("No such change.")
    if change.proposed_by == principal.subject:
        raise Forbidden("A second person must decide a change you proposed (dual authorisation).")
    pending = change.status == "pending"
    decided = pending and await changes.decide(principal.tenant_id, change_id, approve, principal.subject)
    if not decided:
        raise InvariantViolated("This change has already been decided.")
    await audit.append(_event(principal, "change.approved" if approve else "change.rejected", str(change_id), reason))
    if approve:
        key, enabled = str(change.payload["key"]), bool(change.payload["enabled"])
        await set_flag(flags, audit, principal, key, enabled, f"approved change {change_id}: {change.reason}")
