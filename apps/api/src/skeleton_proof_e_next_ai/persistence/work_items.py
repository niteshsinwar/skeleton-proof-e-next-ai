"""EXAMPLE SLICE — work-item repository. Rows are rebuilt through the domain constructor (02/B6)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.work_items import State, WorkItem
from .schema import work_items


def _to_domain(row: Any) -> WorkItem:
    return WorkItem(
        id=row.id,
        tenant_id=row.tenant_id,
        title=row.title,
        state=State(row.state),
        version=row.version,
        created_by=row.created_by,
        created_at=row.created_at,
        submitted_by=row.submitted_by,
        decided_by=row.decided_by,
        decision_reason=row.decision_reason,
        created_by_name=row.created_by_name,
        decided_by_name=row.decided_by_name,
    )


class PgWorkItems:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def add(self, item: WorkItem) -> None:
        await self.conn.execute(
            insert(work_items).values(
                id=item.id,
                tenant_id=item.tenant_id,
                title=item.title,
                state=item.state.value,
                version=item.version,
                created_by=item.created_by,
                created_by_name=item.created_by_name,
                created_at=item.created_at,
                updated_at=item.created_at,
            )
        )

    async def get(self, item_id: UUID) -> WorkItem | None:
        row = (await self.conn.execute(select(work_items).where(work_items.c.id == item_id))).first()
        return _to_domain(row) if row else None

    async def save(self, item: WorkItem, expected_version: int) -> bool:
        """Optimistic concurrency (02/D14): the update only lands on the version the caller read."""
        result = await self.conn.execute(
            update(work_items)
            .where(work_items.c.id == item.id, work_items.c.version == expected_version)
            .values(
                state=item.state.value,
                version=item.version,
                submitted_by=item.submitted_by,
                decided_by=item.decided_by,
                decided_by_name=item.decided_by_name,
                decision_reason=item.decision_reason,
                updated_at=datetime.now(UTC),
            )
        )
        return result.rowcount == 1

    async def list(self, *, created_by: str | None, after: UUID | None, limit: int) -> list[WorkItem]:
        q = select(work_items).order_by(work_items.c.id).limit(limit)
        if created_by is not None:
            q = q.where(work_items.c.created_by == created_by)
        if after is not None:
            q = q.where(work_items.c.id > after)
        return [_to_domain(r) for r in (await self.conn.execute(q)).all()]
