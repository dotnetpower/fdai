"""Conversation model traces become Phoenix spans, with content only on explicit opt-in."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fdai.delivery.azure.llm.model_trace import (
    clear_model_trace_observers,
    complete_model_trace,
    register_model_trace_observer,
    start_model_trace,
)
from fdai.delivery.phoenix import (
    AppInsightsLlmTraceConfig,
    AppInsightsLlmTraceSink,
    PhoenixMeteringSink,
    apply_app_insights_llm_settings,
    phoenix_config_from_env,
)
from fdai.shared.telemetry.correlation import with_correlation
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_MESSAGES = [
    {"role": "system", "content": "You answer operator questions."},
    {"role": "user", "content": "Why is the checkout slow?"},
]
_USAGE = {
    "prompt_tokens": 80,
    "completion_tokens": 20,
    "prompt_tokens_details": {"cached_tokens": 8},
}


@pytest.fixture(autouse=True)
def _isolated_observers() -> Iterator[None]:
    clear_model_trace_observers()
    yield
    clear_model_trace_observers()


def _run_call(sink: PhoenixMeteringSink) -> None:
    register_model_trace_observer(sink.record_model_trace)
    start = start_model_trace(_MESSAGES)
    with with_correlation("conv-7"):
        complete_model_trace(
            start,
            call_id="adaptive-1",
            kind="adaptive-answer",
            model="gpt-test",
            response_content="Latency rose after the 14:02 deploy.",
            usage=_USAGE,
        )


def test_trace_span_without_content_has_timing_tokens_and_hashes_only() -> None:
    exporter = InMemorySpanExporter()
    _run_call(PhoenixMeteringSink(exporter=exporter, batch=False))

    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert span.name == "llm.adaptive-answer"
    assert attrs["session.id"] == "conv-7"
    assert attrs["llm.model_name"] == "gpt-test"
    assert attrs["llm.token_count.prompt"] == 80
    assert attrs["llm.token_count.completion"] == 20
    assert attrs["llm.token_count.prompt_details.cache_read"] == 8
    assert attrs["fdai.request_sha256"] != "" and attrs["fdai.response_sha256"] != ""
    assert not {
        k for k in attrs if k.startswith(("input.", "output.", "llm.input_", "llm.output_"))
    }
    assert span.end_time is not None and span.start_time is not None
    assert span.end_time >= span.start_time


def test_trace_span_with_content_carries_the_redacted_messages() -> None:
    exporter = InMemorySpanExporter()
    _run_call(PhoenixMeteringSink(exporter=exporter, batch=False, capture_content=True))

    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert attrs["input.value"] == "Why is the checkout slow?"
    assert attrs["output.value"] == "Latency rose after the 14:02 deploy."
    assert attrs["llm.input_messages.0.message.role"] == "system"
    assert attrs["llm.input_messages.1.message.content"] == "Why is the checkout slow?"
    assert attrs["llm.output_messages.0.message.role"] == "assistant"


def test_secrets_are_redacted_before_they_reach_the_span() -> None:
    exporter = InMemorySpanExporter()
    sink = PhoenixMeteringSink(exporter=exporter, batch=False, capture_content=True)
    register_model_trace_observer(sink.record_model_trace)
    start = start_model_trace(
        [{"role": "user", "content": "token=Bearer abcdefghijklmnopqrstuvwxyz0123456789"}]
    )
    complete_model_trace(start, call_id="c", kind="k", model="m", response_content="ok", usage=None)

    (span,) = exporter.get_finished_spans()
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in str(dict(span.attributes or {}))


def test_failing_observer_never_breaks_the_model_call() -> None:
    def broken(_: object) -> None:
        raise RuntimeError("observer down")

    register_model_trace_observer(broken)
    trace = complete_model_trace(
        start_model_trace(_MESSAGES),
        call_id="c",
        kind="k",
        model="m",
        response_content="ok",
        usage=None,
    )
    assert trace["kind"] == "k"


def test_content_capture_is_loopback_only_and_off_by_default() -> None:
    base = {
        "FDAI_PHOENIX_TRACING_ENABLED": "1",
        "FDAI_PHOENIX_OTLP_ENDPOINT": "http://127.0.0.1:4317",
    }
    default = phoenix_config_from_env(base)
    assert default is not None and default.capture_content is False
    enabled = phoenix_config_from_env({**base, "FDAI_PHOENIX_CAPTURE_CONTENT": "1"})
    assert enabled is not None and enabled.capture_content is True
    remote = phoenix_config_from_env(
        {
            **base,
            "FDAI_PHOENIX_OTLP_ENDPOINT": "https://phoenix.example.net:4317",
            "FDAI_PHOENIX_ALLOW_REMOTE_ENDPOINT": "1",
            "FDAI_PHOENIX_CAPTURE_CONTENT": "1",
        }
    )
    assert remote is None


def test_app_insights_sink_exports_redacted_prompt_and_response_when_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("fdai.telemetry.llm")
    logger = logging.getLogger("fdai.telemetry.llm")
    sink = AppInsightsLlmTraceSink(
        tracer=tracer,
        logger=logger,
        config=AppInsightsLlmTraceConfig(tracing_enabled=False, capture_content=True),
    )
    register_model_trace_observer(sink.record_model_trace)

    with caplog.at_level(logging.INFO, logger="fdai.telemetry.llm"), with_correlation("conv-ai-1"):
        complete_model_trace(
            start_model_trace(_MESSAGES),
            call_id="t2-proposer-1",
            kind="t2-proposer",
            model="gpt-test",
            response_content='{"abstain":false,"action_type":"restart"}',
            usage=_USAGE,
            usage_scope="control_plane",
        )

    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert span.name == "llm.t2-proposer"
    assert attrs["fdai.usage_scope"] == "control_plane"
    assert attrs["session.id"] == "conv-ai-1"
    assert attrs["input.value"] == "Why is the checkout slow?"
    assert attrs["llm.input_messages.0.message.content"] == "You answer operator questions."
    assert attrs["llm.input_messages.1.message.content"] == "Why is the checkout slow?"
    assert attrs["output.value"] == '{"abstain":false,"action_type":"restart"}'
    records = [r for r in caplog.records if r.msg == "llm_model_trace"]
    assert len(records) == 1
    assert records[0].__dict__["llm_capture_content"] is True
    assert records[0].__dict__["llm_trace"]["request"]["messages"][1]["content"] == (
        "Why is the checkout slow?"
    )


def test_app_insights_sink_switches_on_runtime_settings_without_restart() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    env = {
        "APPLICATIONINSIGHTS_CONNECTION_STRING": (
            "InstrumentationKey=00000000-0000-0000-0000-000000000000"
        )
    }
    sink = AppInsightsLlmTraceSink(
        tracer=provider.get_tracer("fdai.telemetry.llm"),
        env=env,
    )
    register_model_trace_observer(sink.record_model_trace)

    complete_model_trace(
        start_model_trace(_MESSAGES),
        call_id="call-off",
        kind="adaptive-answer",
        model="gpt-test",
        response_content="ignored while off",
        usage=_USAGE,
    )
    assert exporter.get_finished_spans() == ()

    apply_app_insights_llm_settings(
        {
            "logging.app_insights.llm_tracing.enabled": True,
            "logging.app_insights.llm_prompt_capture.enabled": True,
        },
        env=env,
    )
    complete_model_trace(
        start_model_trace(_MESSAGES),
        call_id="call-on",
        kind="adaptive-answer",
        model="gpt-test",
        response_content="captured after settings update",
        usage=_USAGE,
    )
    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert attrs["input.value"] == "Why is the checkout slow?"
    assert attrs["output.value"] == "captured after settings update"
