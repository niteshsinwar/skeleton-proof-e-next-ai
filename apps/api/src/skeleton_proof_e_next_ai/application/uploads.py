"""Accept an upload: validated intake, a server-generated name, storage outside the web root, audit (05/SG6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..domain.ids import new_id
from ..domain.ports import AuditEvent, AuditPort, BlobStore, UploadLog
from ..domain.principals import Capability, Principal


@dataclass(frozen=True, slots=True)
class AcceptedUpload:
    id: UUID
    stored_name: str
    media_type: str
    size_bytes: int


async def accept(
    store: BlobStore,
    log: UploadLog,
    audit: AuditPort,
    principal: Principal,
    data: bytes,
    media_type: str,
    extension: str,
    now: datetime,
) -> AcceptedUpload:
    principal.require(Capability.UPLOAD_CREATE)
    upload_id = new_id()
    stored = f"{upload_id}{extension}"  # never the client's filename
    await store.put(stored, data)
    await log.add(
        upload_id, principal.tenant_id, stored, media_type, len(data), principal.on_behalf_of or principal.subject, now
    )
    await audit.append(
        AuditEvent(
            action="upload.accepted",
            entity="upload",
            entity_id=str(upload_id),
            actor=principal.subject,
            principal_kind=principal.kind.value,
            on_behalf_of=principal.on_behalf_of,
            tenant_id=principal.tenant_id,
            before_version=None,
            after_version=None,
            reason=f"{media_type}, {len(data)} bytes at {now.isoformat()}",
        )
    )
    return AcceptedUpload(id=upload_id, stored_name=stored, media_type=media_type, size_bytes=len(data))
