"""RFC 9457 problem details (02/A6, 02/A7): stable code, correlation id, user-safe detail.

No stack trace, SQL, secret or raw provider text ever reaches `detail`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..domain.errors import DomainError, IllegalTransition
from ..telemetry import context

log = logging.getLogger(__name__)
PROBLEM = "application/problem+json"


class ProblemError(Exception):
    """An HTTP-level problem raised by the API layer itself (missing If-Match, auth, limits)."""

    def __init__(self, status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.headers = status, code, detail, headers or {}


def problem(status: int, code: str, detail: str, request: Request, **extra: Any) -> JSONResponse:
    body = {
        "type": f"https://errors.example/{code}",
        "title": code.replace("-", " "),
        "status": status,
        "code": code,
        "detail": detail,
        "instance": request.url.path,
        "correlation_id": context.correlation_id.get(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def install(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        resp = problem(exc.status, exc.code, exc.detail, request)
        resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        extra: dict[str, Any] = {}
        if isinstance(exc, IllegalTransition):
            extra["legal_transitions"] = exc.legal
        resp = problem(exc.status, exc.code, exc.detail, request, **extra)
        if exc.status in (429, 503):
            resp.headers["Retry-After"] = str(getattr(exc, "retry_after", None) or 60)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return problem(422, "validation-failed", "The request did not match the contract.", request, errors=fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return problem(exc.status_code, code, "The request could not be served.", request)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return problem(500, "internal-error", "Something went wrong; quote the correlation id.", request)
