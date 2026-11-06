"""Retiring a route (02/A10): Deprecation (RFC 9745), Sunset (RFC 8594) and a deprecation link before the sunset,
410 at and after it, and the OpenAPI marks oasdiff reads (`deprecated`, `x-sunset`)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

from skeleton_proof_e_next_ai.api import deprecation, errors
from skeleton_proof_e_next_ai.api.deps import now

DEPRECATED, SUNSET, LINK = date(2026, 1, 1), date(2026, 7, 1), "https://docs.example/v1-items"


class Item(BaseModel):
    id: int


def client(at: datetime) -> TestClient:
    app = FastAPI()
    errors.install(app)
    deprecation.install(app)
    app.dependency_overrides[now] = lambda: at  # time is injected, never read from the wall clock (06/T4)
    retire = deprecation.retiring(deprecated=DEPRECATED, sunset=SUNSET, link=LINK)

    @app.get("/v1/items/{item_id}", **retire)
    async def as_model(item_id: int) -> Item:
        return Item(id=item_id)

    @app.get("/v1/raw", **retire)
    async def as_response() -> Response:  # a route returning its own Response must announce it too
        return Response("ok", media_type="text/plain")

    @app.get("/v2/items/{item_id}")
    async def current(item_id: int) -> Item:
        return Item(id=item_id)

    return TestClient(app)


@pytest.mark.parametrize("path", ["/v1/items/7", "/v1/raw"])
def test_before_the_sunset_a_retiring_route_answers_and_announces_it(path: str) -> None:
    r = client(datetime(2026, 6, 30, 23, 59, tzinfo=UTC)).get(path)
    assert r.status_code == 200
    assert r.headers["Deprecation"] == "@1767225600"  # 2026-01-01T00:00:00Z as an RFC 9651 Date
    assert r.headers["Sunset"] == "Thu, 02 Jul 2026 00:00:00 GMT"  # PLANTED FAULT: the gate must go red
    assert r.headers["Link"] == f'<{LINK}>; rel="deprecation"'


@pytest.mark.parametrize("path", ["/v1/items/7", "/v1/raw"])
def test_from_the_sunset_a_retired_route_is_gone_with_a_problem_body(path: str) -> None:
    r = client(datetime(2026, 7, 1, 0, 0, tzinfo=UTC)).get(path)
    assert r.status_code == 410
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "gone"
    assert LINK in r.json()["detail"]
    assert r.headers["Sunset"] == "Wed, 01 Jul 2026 00:00:00 GMT"  # still says when, and where to go


def test_a_current_route_carries_no_retirement_headers() -> None:
    r = client(datetime(2026, 6, 1, tzinfo=UTC)).get("/v2/items/7")
    assert r.status_code == 200
    assert "Deprecation" not in r.headers and "Sunset" not in r.headers and "Link" not in r.headers


def test_the_openapi_marks_what_the_breaking_change_check_reads() -> None:
    spec = client(datetime(2026, 6, 1, tzinfo=UTC)).get("/openapi.json").json()
    retiring = spec["paths"]["/v1/items/{item_id}"]["get"]
    assert retiring["deprecated"] is True
    assert retiring["x-sunset"] == "2026-07-01"  # an RFC 3339 full-date, as oasdiff expects
    assert "deprecated" not in spec["paths"]["/v2/items/{item_id}"]["get"]


def test_a_sunset_before_the_deprecation_is_refused() -> None:
    with pytest.raises(ValueError, match="sunset"):
        deprecation.retiring(deprecated=SUNSET, sunset=DEPRECATED, link=LINK)
    deprecation.retiring(deprecated=SUNSET, sunset=SUNSET, link=LINK)  # the same day is allowed (RFC 9745 §4)
