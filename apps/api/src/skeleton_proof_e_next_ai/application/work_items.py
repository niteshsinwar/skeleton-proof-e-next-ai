"""EXAMPLE SLICE — work-item use cases. Load → authorise → decide via the domain → persist → audit → publish.

Use cases receive ports, never adapters, and never commit (02/A3). Objects the caller may not see are
reported exactly like objects that don't exist (02/A7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..domain.errors import FeatureDisabled, Forbidden, IllegalTransition, InvariantViolated, NotFound, VersionMismatch
from ..domain.ids import new_id
from ..domain.ports import AuditEvent, AuditPort, FlagPort, OutboxPort, WorkItemRepository
from ..domain.principals import Capability, Principal
from ..domain.work_items import Command, State, WorkItem
from ..workflow.work_items import legal_commands, next_state

FEATURE = "work_items"
ENTITY = "work_item"


@dataclass(frozen=True, slots=True)
class Ports:
    items: WorkItemRepository
    audit: AuditPort
    outbox: OutboxPort
    flags: FlagPort


async def _feature_on(ports: Ports, principal: Principal) -> None:
    if not await ports.flags.enabled(FEATURE, principal.tenant_id):
        raise FeatureDisabled("Work items are switched off for now.")


def _owner(principal: Principal) -> str:
    return principal.on_behalf_of or principal.subject


async def _audit(
    ports: Ports, principal: Principal, action: str, item: WorkItem, before: int | None, reason: str | None = None
) -> None:
    await ports.audit.append(
        AuditEvent(
            action=action,
            entity=ENTITY,
            entity_id=str(item.id),
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=before,
            after_version=item.version,
            reason=reason,
        )
    )


def _visible(item: WorkItem | None, principal: Principal) -> WorkItem:
    if (
        item is None
        or item.tenant_id != principal.tenant_id
        or (item.created_by != _owner(principal) and not principal.can(Capability.WORK_ITEM_READ_ALL))
    ):
        raise NotFound("No such work item.")
    return item


async def create(ports: Ports, principal: Principal, title: str, now: datetime, max_title: int) -> WorkItem:
    principal.require(Capability.WORK_ITEM_CREATE)
    await _feature_on(ports, principal)
    if len(title) > max_title:
        raise InvariantViolated(f"A title is at most {max_title} characters under the current policy.")
    item = WorkItem(
        id=new_id(),
        tenant_id=principal.tenant_id,
        title=title,
        state=State.DRAFT,
        version=1,
        created_by=_owner(principal),
        created_at=now,
        created_by_name=principal.name,
    )
    await ports.items.add(item)
    await _audit(ports, principal, "work_item.created", item, None)
    await ports.outbox.publish(ENTITY, item.id, item.version, "work_item.created", {"id": str(item.id)})
    return item


async def get(ports: Ports, principal: Principal, item_id: UUID) -> WorkItem:
    return _visible(await ports.items.get(item_id), principal)


async def list_items(ports: Ports, principal: Principal, after: UUID | None, limit: int) -> list[WorkItem]:
    created_by = None if principal.can(Capability.WORK_ITEM_READ_ALL) else _owner(principal)
    return await ports.items.list(created_by=created_by, after=after, limit=limit)


async def run_command(
    ports: Ports,
    principal: Principal,
    item_id: UUID,
    command: Command,
    expected_version: int,
    reason: str | None = None,
) -> WorkItem:
    principal.require(Capability.WORK_ITEM_CREATE if command is Command.SUBMIT else Capability.WORK_ITEM_DECIDE)
    await _feature_on(ports, principal)
    item = _visible(await ports.items.get(item_id), principal)
    if command is Command.SUBMIT and item.created_by != _owner(principal):
        raise Forbidden("Only the item's owner can submit it.")
    if item.version != expected_version:
        raise VersionMismatch("The item changed since you read it; reload and try again.")
    target = next_state(item.state, command)
    if target is None:
        raise IllegalTransition(
            f"'{command.value}' is not allowed from '{item.state.value}'.",
            [c.value for c in legal_commands(item.state)],
        )
    updated = item.transition(command, target, actor=_owner(principal), reason=reason, actor_name=principal.name)
    if not await ports.items.save(updated, expected_version):
        raise VersionMismatch("The item changed since you read it; reload and try again.")
    await _audit(ports, principal, f"work_item.{command.value}", updated, item.version, reason)
    await ports.outbox.publish(
        ENTITY,
        updated.id,
        updated.version,
        f"work_item.{updated.state.value}",
        {"id": str(updated.id), "state": updated.state.value},
    )
    return updated
