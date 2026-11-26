"""OpenTelemetry tracing wiring emits spans."""

from __future__ import annotations

from fdai.shared.telemetry import get_tracer, with_correlation
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _install_in_memory_provider() -> InMemorySpanExporter:
    """Force a fresh in-memory provider for the test.

    OTel forbids replacing the global provider, so we install one here
    only when nothing else has claimed it. In this suite, the module
    ``configure_tracing`` may have run in a prior test - either way we
    add our own SimpleSpanProcessor to the *current* provider so spans
    reach an inspectable exporter.
    """
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    # If this is the default no-op provider, install a real SDK one first.
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": "fdai-test"}))
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_span_is_emitted() -> None:
    exporter = _install_in_memory_provider()
    tracer = get_tracer("fdai.tests.telemetry")

    with tracer.start_as_current_span("t0.evaluate") as span:
        span.set_attribute("aw.tier", "t0")

    spans = exporter.get_finished_spans()
    matching = [s for s in spans if s.name == "t0.evaluate"]
    assert matching, f"span t0.evaluate not found in {[s.name for s in spans]}"
    attrs = dict(matching[-1].attributes or {})
    assert attrs.get("aw.tier") == "t0"


def test_correlation_can_be_attached_to_a_span() -> None:
    """The Protocol only requires that spans + logs share the same id.

    We record it as a span attribute so the audit trail joins on it.
    """
    exporter = _install_in_memory_provider()
    tracer = get_tracer("fdai.tests.telemetry")

    with with_correlation("evt-99"), tracer.start_as_current_span("risk.gate") as span:
        span.set_attribute("aw.correlation_id", "evt-99")

    spans = exporter.get_finished_spans()
    risk_spans = [s for s in spans if s.name == "risk.gate"]
    assert risk_spans
    attrs = dict(risk_spans[-1].attributes or {})
    assert attrs.get("aw.correlation_id") == "evt-99"
