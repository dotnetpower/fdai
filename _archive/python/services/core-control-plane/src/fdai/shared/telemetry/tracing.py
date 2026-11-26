"""OpenTelemetry tracing wiring.

Day-zero exporter is :class:`ConsoleSpanExporter` - spans print to stderr,
so a developer running the loop locally sees the tier/gate/audit chain
without any collector. OTLP export lands with W4.1 (collector deployment).

Consumers depend on ``opentelemetry.trace`` in the usual way:

.. code-block:: python

    from fdai.shared.telemetry import get_tracer, with_correlation

    tracer = get_tracer(__name__)
    with with_correlation("evt-42"), tracer.start_as_current_span("t0.evaluate"):
        # ... work; span carries the correlation id via a span attribute
        ...
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)

_CONFIGURED = False


def configure_tracing(
    service_name: str,
    env: str,
    *,
    otlp_endpoint: str | None = None,
    otlp_insecure: bool = False,
) -> None:
    """Install a :class:`TracerProvider` if one has not been installed yet.

    Idempotent - a repeat call is a no-op. OTel forbids replacing the
    global provider once set.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "runtime.env": env,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter: SpanExporter
    if otlp_endpoint is None:
        exporter = ConsoleSpanExporter()
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=otlp_insecure)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def get_tracer(name: str) -> trace.Tracer:
    """Return an OTel tracer keyed by ``name`` (typically ``__name__``)."""
    return trace.get_tracer(name)


__all__ = ["configure_tracing", "get_tracer"]
