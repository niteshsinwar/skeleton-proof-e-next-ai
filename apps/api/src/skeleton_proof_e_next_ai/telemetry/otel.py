"""Traces and metrics through OpenTelemetry (07/O7-O9, 13/SK7), exported over OTLP/HTTP only when an endpoint is set.

Without APP_OTEL_ENDPOINT spans and metrics go nowhere: no backend is needed to run, test or demo (01/C4). Langfuse
(tiers S and E) or Phoenix (tier P, local) receive them when a project points the endpoint at one. Our own records
stay the truth (audit events, AI attempts); spans are a view of them, and an AI attempt is mapped to the
`gen_ai.*` conventions here, at export, because those conventions are still in development (07/O9; read 2026-11-06
in OpenTelemetry's repository of conventions for generative AI).

Metric attributes come from a fixed allowlist: ids, paths and users go in spans and logs, never in metric labels,
where every distinct value is a new time series (07/O8).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

# The only attribute keys a metric may carry (07/O8). Anything else is refused when it is recorded.
METRIC_ATTRIBUTES = frozenset({"http.request.method", "http.route", "http.response.status_code"})


class HighCardinalityAttribute(ValueError):
    pass


def metric_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(attributes) - METRIC_ATTRIBUTES
    if unknown:
        raise HighCardinalityAttribute(f"metric attributes outside the allowlist (07/O8): {sorted(unknown)}")
    return dict(attributes)


@dataclass
class Telemetry:
    tracer: Tracer
    meter: Meter
    request_duration: Histogram
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def record_request(self, seconds: float, method: str, route: str, status: int) -> None:
        """RED for one request (07/O8): rate and errors come from the count by status, duration from the histogram."""
        attrs = {"http.request.method": method, "http.route": route, "http.response.status_code": status}
        self.request_duration.record(seconds, metric_attributes(attrs))

    def shutdown(self) -> None:
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def configure(
    service: str,
    version: str,
    environment: str,
    endpoint: str | None,
    *,
    span_processors: Sequence[SpanProcessor] = (),
    metric_readers: Sequence[MetricReader] = (),
) -> Telemetry:
    """This process's providers. Tests pass in-memory processors and readers; a deployment passes an endpoint."""
    resource = Resource.create(
        {"service.name": service, "service.version": version, "deployment.environment.name": environment}
    )
    tracer_provider = TracerProvider(resource=resource)
    for processor in span_processors:
        tracer_provider.add_span_processor(processor)
    readers = list(metric_readers)
    if endpoint:
        base = endpoint.rstrip("/")
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces")))
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{base}/v1/metrics")))
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    meter = meter_provider.get_meter("app")
    return Telemetry(
        tracer=tracer_provider.get_tracer("app"),
        meter=meter,
        request_duration=meter.create_histogram(
            "http.server.request.duration", unit="s", description="Duration of HTTP server requests (07/O8)"
        ),
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )


SERVER = SpanKind.SERVER


def finish_request_span(span: Span, method: str, route: str, status: int, correlation_id: str) -> None:
    span.update_name(f"{method} {route}")
    span.set_attribute("http.request.method", method)
    span.set_attribute("http.route", route)
    span.set_attribute("http.response.status_code", status)
    span.set_attribute("app.correlation_id", correlation_id)  # high-cardinality: spans and logs only (07/O8)
    if status >= 500:
        span.set_status(Status(StatusCode.ERROR))


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000_000)


def attempt_span(
    tracer: Tracer,
    *,
    attempt_id: str,
    step: str,
    status: str,
    mode: str,
    provider: str | None,
    requested_model: str | None,
    served_model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int | None,
    cache_write_tokens: int | None,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    """One recorded AI attempt as a `gen_ai` client span, after the fact: the attempt record is the source (07/O9).

    Unknown counts stay absent, never zero (04/M3). Anthropic reports cached input apart from `input_tokens`, and the
    conventions require `gen_ai.usage.input_tokens` to include it, so the total is computed here.
    """
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "chat",
        "app.attempt_id": attempt_id,  # joins the span to its record, so tracing is proven from the store (07/O11)
        "app.step": step,
        "app.attempt.status": status,
        "app.attempt.mode": mode,
    }
    if provider:
        attributes["gen_ai.provider.name"] = provider
    if requested_model:
        attributes["gen_ai.request.model"] = requested_model
    if served_model:
        attributes["gen_ai.response.model"] = served_model
    if input_tokens is not None:
        cached = (cache_read_tokens or 0) + (cache_write_tokens or 0) if provider == "anthropic" else 0
        attributes["gen_ai.usage.input_tokens"] = input_tokens + cached
    if output_tokens is not None:
        attributes["gen_ai.usage.output_tokens"] = output_tokens
    if cache_read_tokens:
        attributes["gen_ai.usage.cache_read.input_tokens"] = cache_read_tokens
    if cache_write_tokens:
        attributes["gen_ai.usage.cache_write.input_tokens"] = cache_write_tokens
    span = tracer.start_span(
        f"chat {requested_model or step}", kind=SpanKind.CLIENT, attributes=attributes, start_time=_ns(started_at)
    )
    if status not in ("succeeded", "abstained"):  # an abstention is an answer, not an error (04/Q5)
        span.set_status(Status(StatusCode.ERROR, status))
    span.end(end_time=_ns(finished_at))
