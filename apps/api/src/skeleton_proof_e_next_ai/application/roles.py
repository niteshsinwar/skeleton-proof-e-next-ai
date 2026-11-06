"""Granting and revoking roles (02/Z5, Z6): admins only, never for themselves, every change audited.

Roles live in the API's grants table, read on every call, so a revoked role stops working on the next request
(02/Z4). Only roles the capability matrix knows can be granted: a typo can't create a role that silently grants
nothing.
"""

from __future__ import annotations

from ..domain.errors import Forbidden, InvariantViolated
from ..domain.ports import AuditEvent, AuditPort, GrantsPort
from ..domain.principals import ROLE_CAPABILITIES, Capability, Principal


async def change_role(
    grants: GrantsPort, audit: AuditPort, principal: Principal, subject: str, role: str, reason: str, *, grant: bool
) -> bool:
    principal.require(Capability.ROLES_MANAGE)
    if subject == principal.subject:
        raise Forbidden("No one can change their own roles (separation of duties).")
    if role not in ROLE_CAPABILITIES:
        raise InvariantViolated(f"'{role}' is not a role; known roles: {', '.join(sorted(ROLE_CAPABILITIES))}.")
    if not reason.strip():
        raise InvariantViolated("Changing a role needs a reason.")
    change = grants.grant if grant else grants.revoke
    changed = await change(principal.tenant_id, subject, role, principal.subject)
    if changed:
        await audit.append(
            AuditEvent(
                action="role.granted" if grant else "role.revoked",
                entity="role_grant",
                entity_id=f"{subject}:{role}",
                actor=principal.subject,
                principal_kind=principal.kind.value,
                on_behalf_of=principal.on_behalf_of,
                tenant_id=principal.tenant_id,
                before_version=None,
                after_version=None,
                reason=reason,
            )
        )
    return changed
