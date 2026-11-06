"""Platform routes: health and readiness (02/A12), session revocation (02/Z4), roles (02/Z5),
kill switches (05/SG11), upload intake (05/SG6)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ...application import flags as flags_uc
from ...application import roles as roles_uc
from ...application import sessions as sessions_uc
from ...application import uploads as uploads_uc
from ...domain.ports import StoredResponse
from ...domain.principals import Principal
from ...persistence import business_config
from ...persistence.files import PgUploadLog
from ...persistence.records import PgAudit, PgChanges, PgFlags, PgGrants, PgIdempotency, PgRevocations
from ...security.uploads import UploadTooLarge, validate
from ..deps import CurrentPrincipal, CurrentToken, IdempotencyKey, now, rate_limited, request_hash, state
from ..errors import problem
from ..schemas.work_items import ChangeDecision, ChangeRole, MeOut, SetFlag, UploadOut

router = APIRouter(tags=["platform"])
ALEMBIC_INI = Path(__file__).resolve().parents[4] / "alembic.ini"


def migration_head() -> str | None:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness plus the build SHA, so every response says which code is running (02/A12)."""
    return {"status": "ok", "sha": state(request).settings.build_sha}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: the database answers as the app role, its migration is the code's head, config loads."""
    st, checks = state(request), {}
    try:
        async with st.db.transaction(tenant_id=None, actor="ready") as conn:
            revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        head = migration_head()
        checks["database"] = "ok"
        checks["migration"] = "ok" if revision == head else f"database at {revision}, code expects {head}"
    except Exception as exc:  # noqa: BLE001  (readiness reports, it doesn't raise)
        checks["database"] = f"unavailable ({type(exc).__name__})"
    try:
        business_config.load(st.settings.business_config_dir)
        checks["business_config"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["business_config"] = f"invalid ({type(exc).__name__})"
    if all(v == "ok" for v in checks.values()) and len(checks) == 3:
        return JSONResponse({"status": "ready", "checks": checks})
    resp = problem(503, "not-ready", "The service is not ready.", request, checks=checks)
    resp.headers["Retry-After"] = "10"
    return resp


@router.post("/session/revoke", status_code=204, dependencies=[rate_limited("write")])
async def revoke_session(request: Request, token: CurrentToken) -> None:
    """End the caller's session now (02/Z4, 03/F40). Naturally idempotent, so no Idempotency-Key (02/A5): revoking
    twice has one effect, and once revoked the token no longer authenticates."""
    principal = token.principal
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        await sessions_uc.revoke(PgRevocations(conn), PgAudit(conn), principal, token.sha256, token.expires_at)


@router.get("/me", response_model=MeOut, dependencies=[rate_limited("read")])
async def me(principal: CurrentPrincipal) -> MeOut:
    """Who the caller is and what they may do, read from the grants on this call: screens use it to offer only what
    will be allowed. An affordance, never a control: every action is still authorised here (03/F9, 02/Z5)."""
    return MeOut(
        subject=principal.subject,
        name=principal.name,
        kind=principal.kind.value,
        roles=sorted(principal.roles),
        capabilities=sorted(c.value for c in principal.capabilities),
    )


async def _change_role(
    subject: str, body: ChangeRole, request: Request, principal: Principal, idempotency_key: str, *, grant: bool
) -> None:
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        verb = "grant" if grant else "revoke"
        scope, digest = f"{principal.subject}:{verb}_role:{subject}", request_hash(body.model_dump())
        if await idem.lookup(scope, idempotency_key, digest) is not None:
            return
        grants, audit = PgGrants(conn), PgAudit(conn)
        await roles_uc.change_role(grants, audit, principal, subject, body.role, body.reason, grant=grant)
        await idem.remember(scope, idempotency_key, digest, StoredResponse(204, {}))


@router.post("/admin/roles/{subject}/grant", status_code=204, dependencies=[rate_limited("write")])
async def grant_role(
    subject: str, body: ChangeRole, request: Request, principal: CurrentPrincipal, idempotency_key: IdempotencyKey
) -> None:
    """Give a person a role (02/Z5): admins only, never themselves (02/Z6), audited; effective on their next call."""
    await _change_role(subject, body, request, principal, idempotency_key, grant=True)


@router.post("/admin/roles/{subject}/revoke", status_code=204, dependencies=[rate_limited("write")])
async def revoke_role(
    subject: str, body: ChangeRole, request: Request, principal: CurrentPrincipal, idempotency_key: IdempotencyKey
) -> None:
    """Take a role away; their next call no longer has it, without waiting for their token to expire (02/Z4)."""
    await _change_role(subject, body, request, principal, idempotency_key, grant=False)


@router.post("/admin/flags/{key}/set", status_code=202, dependencies=[rate_limited("write")])
async def set_flag(
    key: str, body: SetFlag, request: Request, principal: CurrentPrincipal, idempotency_key: IdempotencyKey
) -> JSONResponse:
    """Propose a kill-switch change; it applies only when a different admin approves it (02/Z6, tier E)."""
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        scope, digest = f"{principal.subject}:set_flag:{key}", request_hash(body.model_dump())
        if (stored := await idem.lookup(scope, idempotency_key, digest)) is None:
            changes, audit = PgChanges(conn), PgAudit(conn)
            change_id = await flags_uc.propose_flag(changes, audit, principal, key, body.enabled, body.reason)
            stored = StoredResponse(202, {"change_id": str(change_id)})
            await idem.remember(scope, idempotency_key, digest, stored)
    return JSONResponse(dict(stored.body), status_code=stored.status)


async def _decide(change_id: UUID, body: ChangeDecision, request: Request, principal: Principal, approve: bool) -> None:
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        await flags_uc.decide_change(
            PgChanges(conn), PgFlags(conn), PgAudit(conn), principal, change_id, approve, body.reason
        )


@router.post("/admin/changes/{change_id}/approve", status_code=204, dependencies=[rate_limited("write")])
async def approve_change(change_id: UUID, body: ChangeDecision, request: Request, principal: CurrentPrincipal) -> None:
    """A second admin approves a proposed change, which then applies (dual authorisation, 02/Z6)."""
    await _decide(change_id, body, request, principal, approve=True)


@router.post("/admin/changes/{change_id}/reject", status_code=204, dependencies=[rate_limited("write")])
async def reject_change(change_id: UUID, body: ChangeDecision, request: Request, principal: CurrentPrincipal) -> None:
    await _decide(change_id, body, request, principal, approve=False)


@router.post("/uploads", status_code=201, response_model=UploadOut, dependencies=[rate_limited("upload")])
async def upload(request: Request, principal: CurrentPrincipal, idempotency_key: IdempotencyKey) -> JSONResponse:
    st = state(request)
    cap, chunks, size = st.settings.upload_max_bytes, [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise UploadTooLarge(f"Uploads are at most {cap} bytes.")
        chunks.append(chunk)
    data = b"".join(chunks)
    media_type = request.headers.get("content-type", "")
    extension = validate(media_type, data)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        scope, digest = f"{principal.subject}:upload", request_hash({"sha256": hashlib.sha256(data).hexdigest()})
        if (stored := await idem.lookup(scope, idempotency_key, digest)) is not None:
            return JSONResponse(dict(stored.body), status_code=stored.status)
        accepted = await uploads_uc.accept(
            st.blobs,
            PgUploadLog(conn),
            PgAudit(conn),
            principal,
            data,
            media_type.partition(";")[0].strip().lower(),
            extension,
            now(),
        )
        out = UploadOut(id=accepted.id, media_type=accepted.media_type, size_bytes=accepted.size_bytes)
        stored = StoredResponse(201, out.model_dump(mode="json"))
        await idem.remember(scope, idempotency_key, digest, stored)
    return JSONResponse(dict(stored.body), status_code=201)
