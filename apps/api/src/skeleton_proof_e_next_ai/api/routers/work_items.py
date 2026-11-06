"""EXAMPLE SLICE — work-item routes: named commands, one transaction each, the route commits (02/A1–A5)."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection

from ...application import work_items as uc
from ...domain.ports import StoredResponse
from ...domain.principals import Principal
from ...domain.work_items import Command
from ...persistence.records import PgAudit, PgFlags, PgIdempotency, PgOutbox
from ...persistence.work_items import PgWorkItems
from ..deps import CurrentPrincipal, ExpectedVersion, IdempotencyKey, now, rate_limited, request_hash, state
from ..errors import ProblemError
from ..schemas.work_items import CreateWorkItem, Decide, WorkItemOut, WorkItemPage

router = APIRouter(prefix="/work-items", tags=["work items (example)"])


def _ports(conn: AsyncConnection, principal: Principal) -> uc.Ports:
    return uc.Ports(
        items=PgWorkItems(conn), audit=PgAudit(conn), outbox=PgOutbox(conn, principal.tenant_id), flags=PgFlags(conn)
    )


def _respond(stored: StoredResponse) -> JSONResponse:
    headers = {"ETag": f'"{stored.body["version"]}"'} if "version" in stored.body else {}
    return JSONResponse(dict(stored.body), status_code=stored.status, headers=headers)


def _encode_cursor(last: UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps({"after": str(last)}).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> UUID:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        return UUID(json.loads(raw)["after"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ProblemError(422, "invalid-cursor", "The cursor is not one this API issued.") from exc


async def _command(
    request: Request,
    principal: Principal,
    item_id: UUID,
    command: Command,
    expected: int,
    key: str,
    body: dict[str, Any],
) -> JSONResponse:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        scope, digest = f"{principal.subject}:{command.value}:{item_id}", request_hash({**body, "if_match": expected})
        if (stored := await idem.lookup(scope, key, digest)) is not None:
            return _respond(stored)
        item = await uc.run_command(_ports(conn, principal), principal, item_id, command, expected, body.get("reason"))
        stored = StoredResponse(200, WorkItemOut.of(item).model_dump(mode="json"))
        await idem.remember(scope, key, digest, stored)
    return _respond(stored)


@router.post("", status_code=201, response_model=WorkItemOut, dependencies=[rate_limited("write")])
async def create_work_item(
    body: CreateWorkItem, request: Request, principal: CurrentPrincipal, key: IdempotencyKey
) -> JSONResponse:
    st = state(request)
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        idem = PgIdempotency(conn, principal.tenant_id)
        scope, digest = f"{principal.subject}:create_work_item", request_hash(body.model_dump())
        if (stored := await idem.lookup(scope, key, digest)) is not None:
            return _respond(stored)
        policy = st.business.work_item_policy(now().date())
        item = await uc.create(_ports(conn, principal), principal, body.title, now(), policy.max_title_length)
        stored = StoredResponse(201, WorkItemOut.of(item).model_dump(mode="json"))
        await idem.remember(scope, key, digest, stored)
    return _respond(stored)


@router.get("", response_model=WorkItemPage, dependencies=[rate_limited("read")])
async def list_work_items(
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1)] = 20,
) -> WorkItemPage:
    st = state(request)
    limit = min(limit, st.settings.max_page_size)
    after = _decode_cursor(cursor) if cursor else None
    async with st.db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        items = await uc.list_items(_ports(conn, principal), principal, after, limit + 1)
    page, more = items[:limit], len(items) > limit
    return WorkItemPage(
        items=[WorkItemOut.of(i) for i in page], next_cursor=_encode_cursor(page[-1].id) if more and page else None
    )


@router.get("/{item_id}", response_model=WorkItemOut, dependencies=[rate_limited("read")])
async def get_work_item(item_id: UUID, request: Request, principal: CurrentPrincipal) -> JSONResponse:
    async with state(request).db.transaction(tenant_id=principal.tenant_id, actor=principal.subject) as conn:
        item = await uc.get(_ports(conn, principal), principal, item_id)
    return _respond(StoredResponse(200, WorkItemOut.of(item).model_dump(mode="json")))


@router.post("/{item_id}/submit", response_model=WorkItemOut, dependencies=[rate_limited("write")])
async def submit_work_item(
    item_id: UUID, request: Request, principal: CurrentPrincipal, expected: ExpectedVersion, key: IdempotencyKey
) -> JSONResponse:
    return await _command(request, principal, item_id, Command.SUBMIT, expected, key, {})


@router.post("/{item_id}/approve", response_model=WorkItemOut, dependencies=[rate_limited("write")])
async def approve_work_item(
    item_id: UUID,
    body: Decide,
    request: Request,
    principal: CurrentPrincipal,
    expected: ExpectedVersion,
    key: IdempotencyKey,
) -> JSONResponse:
    return await _command(request, principal, item_id, Command.APPROVE, expected, key, body.model_dump())


@router.post("/{item_id}/reject", response_model=WorkItemOut, dependencies=[rate_limited("write")])
async def reject_work_item(
    item_id: UUID,
    body: Decide,
    request: Request,
    principal: CurrentPrincipal,
    expected: ExpectedVersion,
    key: IdempotencyKey,
) -> JSONResponse:
    return await _command(request, principal, item_id, Command.REJECT, expected, key, body.model_dump())
