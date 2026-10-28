"""Tests for :mod:`fdai.delivery.phoenix.metering_sink`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.usage import TokenUsage
from fdai.delivery.phoenix import PhoenixMeteringSink, phoenix_config_from_env
from fdai.delivery.phoenix.metering_sink import PhoenixTracingConfig
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_ON = {
    "FDAI_PHOENIX_TRACING_ENABLED": "1",
    "FDAI_PHOENIX_OTLP_ENDPOINT": "http://127.0.0.1:4317",
}


def _inv(**overrides: object) -> LlmInvocation:
    fields: dict[str, object] = {
        "occurred_at": datetime(2026, 7, 10, 12, 0, 5, tzinfo=UTC),
        "correlation_id": "conv-1",
        "capability_id": "t2.judge",
        "model_key": "gpt-test",
        "tier": "T2",
        "mode": InvocationMode.ENFORCE,
        "usage": TokenUsage(prompt_tokens=120, completion_tokens=30),
        "cached_prompt_tokens": 20,
        "duration_ms": 2000,
        "cost": Decimal("0.0042"),
        "currency": "USD",
    }
    fields.update(overrides)
    return LlmInvocation(**fields)  # type: ignore[arg-type]


async def test_record_emits_one_openinference_llm_span() -> None:
    exporter = InMemorySpanExporter()
    sink = PhoenixMeteringSink(exporter=exporter, project_name="proj", batch=False)

    await sink.record(_inv())

    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert span.name == "llm.t2.judge"
    assert span.parent is None
    assert attrs["openinference.span.kind"] == "LLM"
    assert attrs["session.id"] == "conv-1"
    assert attrs["llm.model_name"] == "gpt-test"
    assert attrs["llm.token_count.prompt"] == 120
    assert attrs["llm.token_count.completion"] == 30
    assert attrs["llm.token_count.total"] == 150
    assert attrs["llm.token_count.prompt_details.cache_read"] == 20
    assert attrs["fdai.mode"] == "enforce"
    assert attrs["fdai.cost.amount"] == "0.0042"
    assert attrs["fdai.cost.currency"] == "USD"
    assert span.end_time is not None and span.start_time is not None
    assert span.end_time - span.start_time == 2_000_000_000
    assert span.resource.attributes["openinference.project.name"] == "proj"


async def test_span_has_no_content_attributes_and_unpriced_omits_cost() -> None:
    exporter = InMemorySpanExporter()
    sink = PhoenixMeteringSink(exporter=exporter, batch=False)

    await sink.record(_inv(cost=None, currency=None))

    (span,) = exporter.get_finished_spans()
    keys = set(span.attributes or {})
    assert not {k for k in keys if k.startswith(("input.", "output.", "llm.input", "llm.output"))}
    assert "fdai.cost.amount" not in keys


async def test_sink_does_not_touch_the_global_tracer_provider() -> None:
    before = trace.get_tracer_provider()
    PhoenixMeteringSink(exporter=InMemorySpanExporter(), batch=False)
    assert trace.get_tracer_provider() is before


def test_flag_off_by_default_even_with_an_endpoint() -> None:
    assert phoenix_config_from_env({}) is None
    assert phoenix_config_from_env({"FDAI_PHOENIX_OTLP_ENDPOINT": "http://127.0.0.1:4317"}) is None
    assert phoenix_config_from_env({**_ON, "FDAI_PHOENIX_TRACING_ENABLED": "0"}) is None


def test_flag_on_returns_loopback_config_with_default_project() -> None:
    config = phoenix_config_from_env(_ON)
    assert config == PhoenixTracingConfig(endpoint="http://127.0.0.1:4317")
    assert config is not None and config.insecure and config.project_name == "fdai"
    named = phoenix_config_from_env({**_ON, "FDAI_PHOENIX_PROJECT_NAME": "dev"})
    assert named is not None and named.project_name == "dev"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"FDAI_PHOENIX_OTLP_ENDPOINT": ""}, "is not set"),
        ({"FDAI_PHOENIX_OTLP_ENDPOINT": "127.0.0.1:4317"}, "http(s) URL"),
        ({"FDAI_PHOENIX_OTLP_ENDPOINT": "http://phoenix.example.net:4317"}, "not loopback"),
    ],
)
def test_misconfigured_flag_disables_export_with_a_reason(
    overrides: dict[str, str], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert phoenix_config_from_env({**_ON, **overrides}) is None
    assert reason in caplog.records[-1].__dict__["reason"]


def test_remote_endpoint_requires_the_explicit_override() -> None:
    env = {
        **_ON,
        "FDAI_PHOENIX_OTLP_ENDPOINT": "https://phoenix.example.net:4317",
        "FDAI_PHOENIX_ALLOW_REMOTE_ENDPOINT": "true",
    }
    config = phoenix_config_from_env(env)
    assert config is not None and not config.insecure


def test_from_config_builds_a_sink_without_contacting_the_collector() -> None:
    config = phoenix_config_from_env(_ON)
    assert config is not None
    sink = PhoenixMeteringSink.from_config(config)
    sink.shutdown()
