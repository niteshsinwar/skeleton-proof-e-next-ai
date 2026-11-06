"""Retiring a route (02/A10). A breaking change ships as a new version; the old route is marked with `retiring()`:

    @router.get("/v1/items/{item_id}", **retiring(deprecated=date(2026, 1, 1), sunset=date(2026, 7, 1), link=DOCS))

Before the sunset it answers as before and every response says so: `Deprecation` (RFC 9745, a structured Date),
`Sunset` (RFC 8594, an HTTP-date) and `Link: <...>; rel="deprecation"`. From the sunset it answers 410 with a problem
body. The OpenAPI gets `deprecated: true` and `x-sunset`, which the breaking-change check (`make api-diff`, oasdiff)
reads: removing the route before its sunset fails CI, removing it after does not. Dates are UTC midnights.

The headers are added by `install()`'s middleware, not by the dependency's response: FastAPI drops a dependency's
headers when a route returns its own `Response` (0.162 `routing.py`). A route with its own `dependencies=` list
combines them: `dependencies=[*retire["dependencies"], ...]`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time
from email.utils import format_datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response

from .deps import now
from .errors import ProblemError


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=UTC)


def retirement_headers(deprecated: date, sunset: date, link: str) -> dict[str, str]:
    return {
        "Deprecation": f"@{int(_midnight(deprecated).timestamp())}",
        "Sunset": format_datetime(_midnight(sunset), usegmt=True),
        "Link": f'<{link}>; rel="deprecation"',
    }


def retiring(*, deprecated: date, sunset: date, link: str) -> dict[str, Any]:
    """Keyword arguments for a route decorator that retire the route on `sunset`, announced from now on."""
    if sunset < deprecated:
        raise ValueError(f"the sunset ({sunset}) may not come before the deprecation ({deprecated}) (RFC 9745 §4)")
    headers = retirement_headers(deprecated, sunset, link)
    gone_at = _midnight(sunset)

    async def announce(request: Request, at: Annotated[datetime, Depends(now)]) -> None:
        request.state.retirement = headers
        if at >= gone_at:
            raise ProblemError(410, "gone", f"This endpoint was retired on {sunset.isoformat()}; see {link}.")

    return {"deprecated": True, "openapi_extra": {"x-sunset": sunset.isoformat()}, "dependencies": [Depends(announce)]}


def install(app: FastAPI) -> None:
    """Add a retiring route's headers to every response it gives, the 410 included."""

    @app.middleware("http")
    async def announce_retirement(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers.update(getattr(request.state, "retirement", {}))
        return response
