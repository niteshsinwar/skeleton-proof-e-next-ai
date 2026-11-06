"""Traces and metrics (telemetry/otel.py; 07/O7-O9, O11): request spans and RED by route template, no
high-cardinality metric attributes, and AI attempts mapped to `gen_ai` spans checked against the records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from skeleton_proof_e_next_ai.api.app import create_app
from skeleton_proof_e_next_ai.config.settings import Settings
from skeleton_proof_e_next_ai.telemetry import otel

ITEM = "0195a2c0-0000-7000-8000-000000000042"


def telemetry() -> tuple[otel.Telemetry, InMemorySpanExporter, InMemoryMetricReader]:
    spans, reader = InMemorySpanExporter(), InMemoryMetricReader()
    processors = [SimpleSpanProcessor(spans)]
    t = otel.configure("test", "0123abc", "test", None, span_processors=processors, metric_readers=[reader])
    return t, spans, reader


def points(reader: InMemoryMetricReader) -> list[dict[str, Any]]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        dict(p.attributes or {})
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == "http.server.request.duration"
        for p in m.data.data_points
    ]


@pytest.mark.anyio
async def test_each_request_is_a_span_and_a_red_point_named_by_its_route_template() -> None:
    t, spans, reader = telemetry()
    app = create_app(Settings(env="test"), telemetry=t)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get(f"/work-items/{ITEM}")).status_code == 401
    names = {s.name for s in spans.get_finished_spans()}
    assert "GET /health" in names
    routes = {p["http.route"] for p in points(reader)}
    assert "/health" in routes and any("{" in r for r in routes), routes
    flat = repr(points(reader))
    assert ITEM not in flat, "an id from a path reached a metric label (07/O8)"
    assert all(s.attributes and s.attributes.get("app.correlation_id") for s in spans.get_finished_spans())


def test_a_high_cardinality_metric_attribute_is_refused() -> None:
    with pytest.raises(otel.HighCardinalityAttribute, match=r"app\.user"):
        otel.metric_attributes({"http.route": "/health", "app.user": "alice"})
    assert otel.metric_attributes({"http.route": "/health"}) == {"http.route": "/health"}


def attempt(t: otel.Telemetry, **changes: Any) -> None:
    started = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
    values: dict[str, Any] = {
        "attempt_id": "a1",
        "step": "summary",
        "status": "succeeded",
        "mode": "live",
        "provider": "anthropic",
        "requested_model": "claude-opus-5-5",
        "served_model": "claude-opus-5-5",
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_tokens": 30,
        "cache_write_tokens": 5,
        "started_at": started,
        "finished_at": started + timedelta(seconds=2),
    }
    otel.attempt_span(t.tracer, **{**values, **changes})


def test_an_attempt_becomes_a_gen_ai_span_with_anthropic_cache_counted_as_input() -> None:
    t, spans, _ = telemetry()
    attempt(t)
    (span,) = spans.get_finished_spans()
    a = dict(span.attributes or {})
    assert span.name == "chat claude-opus-5-5" and a["gen_ai.provider.name"] == "anthropic"
    assert a["gen_ai.usage.input_tokens"] == 135, "Anthropic's cached input is part of input_tokens in the conventions"
    assert a["gen_ai.usage.output_tokens"] == 20 and a["app.attempt_id"] == "a1"
    assert span.end_time is not None and span.start_time is not None
    assert span.end_time - span.start_time == 2_000_000_000, "the span spans the recorded attempt, not export time"


def test_unknown_usage_stays_absent_and_a_failed_attempt_is_an_error() -> None:
    t, spans, _ = telemetry()
    attempt(t, status="failed", input_tokens=None, output_tokens=None, cache_read_tokens=None, cache_write_tokens=None)
    (span,) = spans.get_finished_spans()
    a = dict(span.attributes or {})
    assert "gen_ai.usage.input_tokens" not in a and "gen_ai.usage.output_tokens" not in a, "unknown is never zero"
    assert span.status.status_code.name == "ERROR"
