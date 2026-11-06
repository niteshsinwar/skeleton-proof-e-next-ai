"""Request dependencies: who is calling, preconditions, limits (02/A4, 02/A5, 02/A13)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Protocol

from fastapi import Depends, Header, Request

from ..config.settings import Settings
from ..domain.ports import AIRunner, ApprovalWorkflow, OutsideTools, Retriever
from ..domain.principals import Principal
from ..persistence.business_config import BusinessConfig
from ..persistence.db import Database
from ..persistence.files import LocalBlobStore
from ..persistence.records import PgGrants, PgRevocations
from ..security.rate_limit import FAIL_CLOSED, LIMITS, Decision, Limit
from ..security.sealed import SecretBox
from .auth import UNAUTHORISED, TokenVerifier, VerifiedToken
from .errors import ProblemError


class Limiter(Protocol):
    async def check(self, key: str, limit: Limit, now: datetime) -> Decision: ...


@dataclass
class AppState:
    settings: Settings
    db: Database
    verifier: TokenVerifier
    mcp_verifier: TokenVerifier  # the same identity provider, the MCP audience (api/mcp.py)
    limiter: Limiter
    blobs: LocalBlobStore
    business: BusinessConfig
    ai: AIRunner
    ai_daily_cap_usd: Decimal
    ai_workflow: ApprovalWorkflow  # plain until the app starts; LangGraph from then on when configured
    ai_executors: Mapping[str, Callable[[Any], Any]]  # proposal kind -> executor factory (api/proposal_kinds.py)
    retriever: Retriever
    mcp_tools: OutsideTools
    mcp_box: SecretBox | None  # seals each tenant's outside-server secrets; None until the key is configured


def state(request: Request) -> AppState:
    s: AppState = request.app.state.core
    return s


def now() -> datetime:
    return datetime.now(UTC)


async def get_token(request: Request, authorization: Annotated[str | None, Header()] = None) -> VerifiedToken:
    """Verify the signature and claims (02/Z1), then refuse a revoked session (02/Z4).

    The revoked-token list and the caller's roles are read on every call. If they can't be read the answer is 503,
    never a pass (02/B7).
    """
    st = state(request)
    return await admit(st, st.verifier.verify(authorization))


async def admit(st: AppState, token: VerifiedToken) -> VerifiedToken:
    """A verified token's live checks: not revoked, and the roles held now (02/Z4, Z5). Shared by every way in."""
    p = token.principal
    try:
        async with st.db.transaction(tenant_id=p.tenant_id, actor=p.subject) as conn:
            revoked = await PgRevocations(conn).is_revoked(token.sha256, now())
            # Roles come from the API's grants, read now, so removing one works on the next call (02/Z4, Z5). An agent
            # holds the roles of the user it acts for, narrowed by its scopes (02/Z7).
            roles = await PgGrants(conn).roles(p.tenant_id, p.on_behalf_of or p.subject)
    except Exception as exc:  # any failure to read the list fails closed
        raise ProblemError(
            503, "auth-unavailable", "Sign-in can't be checked right now; try again shortly.", {"Retry-After": "5"}
        ) from exc
    if revoked:
        raise ProblemError(401, "session-revoked", "This session has ended; sign in again.", UNAUTHORISED)
    return replace(token, principal=replace(p, roles=roles))


CurrentToken = Annotated[VerifiedToken, Depends(get_token)]


async def get_principal(token: CurrentToken) -> Principal:
    return token.principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_if_match(if_match: Annotated[str | None, Header()] = None) -> int:
    """Writes to an existing resource must say which version they read (02/A4)."""
    if if_match is None:
        raise ProblemError(428, "if-match-required", "Send If-Match with the ETag you read.")
    try:
        return int(if_match.strip().removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise ProblemError(412, "version-mismatch", "If-Match does not name a version of this resource.") from exc


def require_idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    """Every side-effecting POST carries a key; retries replay the first result (02/A5)."""
    if not idempotency_key or len(idempotency_key) > 200:
        raise ProblemError(400, "idempotency-key-required", "Send an Idempotency-Key header (at most 200 characters).")
    return idempotency_key


ExpectedVersion = Annotated[int, Depends(require_if_match)]
IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]


def request_hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def rate_limited(endpoint_class: str) -> Any:
    """Per principal, per tenant, per class; humans and agents are separate classes (01/R2, 01/R3)."""

    async def check(request: Request, principal: CurrentPrincipal) -> None:
        limit = LIMITS[endpoint_class][principal.kind.value]
        key = f"{principal.tenant_id}:{principal.kind.value}:{principal.subject}:{endpoint_class}"
        await _enforce(request, key, limit, endpoint_class)

    return Depends(check)


async def _enforce(request: Request, key: str, limit: Limit, endpoint_class: str) -> None:
    try:
        decision = await state(request).limiter.check(key, limit, now())
    except Exception as exc:  # the limiter's own store failing is a decided case (01/R2)
        if FAIL_CLOSED[endpoint_class]:
            raise ProblemError(503, "rate-limiter-unavailable", "Try again shortly.", {"Retry-After": "5"}) from exc
        return
    if not decision.allowed:
        raise ProblemError(
            429, "rate-limited", "Too many requests; slow down.", {"Retry-After": str(decision.retry_after_seconds)}
        )
