"""OpenTelemetry bootstrap for the orchestrator."""

from __future__ import annotations

from typing import Optional


def setup_tracing(service_name: str, otlp_endpoint: Optional[str], enabled: bool) -> None:
    """Initialize OpenTelemetry if dependencies and configuration are available."""
    if not enabled or not otlp_endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:  # pragma: no cover - optional dependency
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()


def instrument_fastapi(app) -> None:
    """Instrument a FastAPI app if OpenTelemetry is available."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except Exception:  # pragma: no cover - optional dependency
        return

    FastAPIInstrumentor.instrument_app(app)
