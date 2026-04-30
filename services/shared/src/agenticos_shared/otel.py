"""OpenTelemetry initialisation.

Call :func:`init_otel` once at process startup. If no endpoint is set,
this is a no-op (so unit tests don't need a collector).
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_INITIALISED = False


def init_otel(
    *,
    service_name: str,
    endpoint: str | None,
    namespace: str = "agenticos",
    extra_resource: dict[str, str] | None = None,
) -> None:
    """Set up the global tracer provider with an OTLP exporter."""

    global _INITIALISED
    if _INITIALISED:
        return

    if not endpoint:
        # No collector configured; leave default no-op tracer in place.
        _INITIALISED = True
        return

    attrs: dict[str, str] = {
        "service.name": service_name,
        "service.namespace": namespace,
    }
    if extra_resource:
        attrs.update(extra_resource)

    provider = TracerProvider(resource=Resource.create(attrs))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _INITIALISED = True


def get_tracer(name: str = "agenticos") -> trace.Tracer:
    return trace.get_tracer(name)
