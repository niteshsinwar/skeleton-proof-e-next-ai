"""Principals and capabilities (02/Z5, 02/Z7).

Three kinds of principal: humans; agents acting for a user (the user's capabilities ∩ the agent's
scopes); services with their own minimal scopes. Authorisation is data: roles map to capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .errors import Forbidden, StepUpRequired


class PrincipalKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SERVICE = "service"


class Capability(StrEnum):
    WORK_ITEM_CREATE = "work_item.create"
    WORK_ITEM_READ_ALL = "work_item.read_all"
    WORK_ITEM_DECIDE = "work_item.decide"
    UPLOAD_CREATE = "upload.create"
    FLAGS_SET = "flags.set"
    AI_INSPECT = "ai.inspect"
    PROPOSALS_READ = "proposals.read"
    PROPOSALS_DECIDE = "proposals.decide"
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_MANAGE = "documents.manage"
    MCP_CONNECT = "mcp.connect"
    ROLES_MANAGE = "roles.manage"


# Role → capability matrix. Change it here, with a test, never in a handler (02/Z5).
ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "member": frozenset({Capability.WORK_ITEM_CREATE, Capability.UPLOAD_CREATE, Capability.DOCUMENTS_READ}),
    "approver": frozenset(
        {
            Capability.WORK_ITEM_CREATE,
            Capability.WORK_ITEM_READ_ALL,
            Capability.WORK_ITEM_DECIDE,
            Capability.AI_INSPECT,
            Capability.PROPOSALS_READ,
            Capability.PROPOSALS_DECIDE,
            Capability.DOCUMENTS_READ,
        }
    ),
    "admin": frozenset(
        {
            Capability.FLAGS_SET,
            Capability.ROLES_MANAGE,
            Capability.WORK_ITEM_READ_ALL,
            Capability.DOCUMENTS_READ,
            Capability.DOCUMENTS_MANAGE,
            Capability.MCP_CONNECT,
        }
    ),
}

# Acts only a human may perform, whatever the scopes say (02/Z14: refusal of AI or system actors on human acts).
HUMAN_ONLY = frozenset(
    {
        Capability.WORK_ITEM_DECIDE,
        Capability.PROPOSALS_DECIDE,
        Capability.FLAGS_SET,
        Capability.ROLES_MANAGE,
        Capability.DOCUMENTS_MANAGE,
        Capability.MCP_CONNECT,
    }
)

# Privileged acts that need a recent phishing-resistant sign-in: required at tier E, offered at S and P (02/Z3, Z4).
STEP_UP: frozenset[Capability] = HUMAN_ONLY


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    kind: PrincipalKind
    tenant_id: UUID
    roles: frozenset[str]
    scopes: frozenset[str] | None = None  # agents and services: what the token was granted
    on_behalf_of: str | None = None  # agents: the user they act for
    stepped_up: bool = False  # signed in recently with a phishing-resistant method (set by the verifier)
    name: str | None = None  # the person's display name from the token, shown instead of the subject (03/F16)

    @property
    def capabilities(self) -> frozenset[Capability]:
        caps: set[Capability] = set()
        for role in self.roles:
            caps |= ROLE_CAPABILITIES.get(role, frozenset())
        if self.kind is not PrincipalKind.HUMAN:
            caps = {c for c in caps if c not in HUMAN_ONLY}
            if self.scopes is not None:
                caps = {c for c in caps if c.value in self.scopes}
        return frozenset(caps)

    def can(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def require(self, cap: Capability) -> None:
        if not self.can(cap):
            raise Forbidden(f"This action needs the '{cap.value}' capability.")
        if cap in STEP_UP and not self.stepped_up:
            raise StepUpRequired("This action needs a recent sign-in with a security key or passkey.")

    @property
    def audit_actor(self) -> str:
        return self.on_behalf_of or self.subject
