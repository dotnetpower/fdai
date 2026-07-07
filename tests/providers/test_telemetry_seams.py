"""Layer-0 telemetry ingestion seams - Protocol conformance + filter semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProvider,
    LogRecord,
    NoopLogQueryProvider,
    StaticLogQueryProvider,
)
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricQuery,
    NoopMetricProvider,
    StaticMetricProvider,
)
from fdai.shared.providers.trace_query import (
    NoopTraceQueryProvider,
    Span,
    StaticTraceQueryProvider,
    TraceQuery,
    TraceQueryProvider,
)

T0 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Protocol conformance - runtime_checkable satisfied by upstream defaults
# ---------------------------------------------------------------------------


def test_metric_noop_conforms_to_protocol() -> None:
    assert isinstance(NoopMetricProvider(), MetricProvider)


def test_log_noop_conforms_to_protocol() -> None:
    assert isinstance(NoopLogQueryProvider(), LogQueryProvider)


def test_trace_noop_conforms_to_protocol() -> None:
    assert isinstance(NoopTraceQueryProvider(), TraceQueryProvider)


# ---------------------------------------------------------------------------
# Noop returns empty for any query
# ---------------------------------------------------------------------------


async def test_metric_noop_returns_empty() -> None:
    provider = NoopMetricProvider()
    got = [p async for p in provider.query(MetricQuery(metric_name="anything"))]
    assert got == []


async def test_log_noop_returns_empty() -> None:
    provider = NoopLogQueryProvider()
    got = [r async for r in provider.query(LogQuery(expression=""))]
    assert got == []


async def test_trace_noop_returns_empty() -> None:
    provider = NoopTraceQueryProvider()
    got = [s async for s in provider.query(TraceQuery())]
    assert got == []


# ---------------------------------------------------------------------------
# StaticMetricProvider - filter semantics
# ---------------------------------------------------------------------------


@pytest.fixture
def metric_samples() -> list[MetricPoint]:
    return [
        MetricPoint("cpu", T0, 0.3, {"resource_id": "vm-a"}),
        MetricPoint("cpu", T0 + timedelta(seconds=30), 0.4, {"resource_id": "vm-a"}),
        MetricPoint("cpu", T0 + timedelta(seconds=60), 0.9, {"resource_id": "vm-b"}),
        MetricPoint("mem", T0, 0.5, {"resource_id": "vm-a"}),
    ]


async def test_metric_static_filters_by_name(metric_samples: list[MetricPoint]) -> None:
    provider = StaticMetricProvider(metric_samples)
    got = [p async for p in provider.query(MetricQuery(metric_name="cpu"))]
    assert len(got) == 3
    assert all(p.metric_name == "cpu" for p in got)


async def test_metric_static_filters_by_labels(metric_samples: list[MetricPoint]) -> None:
    provider = StaticMetricProvider(metric_samples)
    got = [
        p
        async for p in provider.query(
            MetricQuery(metric_name="cpu", labels={"resource_id": "vm-a"})
        )
    ]
    assert [p.value for p in got] == [0.3, 0.4]


async def test_metric_static_filters_by_time_window(metric_samples: list[MetricPoint]) -> None:
    provider = StaticMetricProvider(metric_samples)
    since = T0 + timedelta(seconds=15)
    got = [p async for p in provider.query(MetricQuery(metric_name="cpu", since=since))]
    assert [p.value for p in got] == [0.4, 0.9]


# ---------------------------------------------------------------------------
# StaticLogQueryProvider - filter semantics + limit
# ---------------------------------------------------------------------------


async def test_log_static_matches_substring_and_labels() -> None:
    records = [
        LogRecord(T0, "startup complete", "info", {"service": "api"}),
        LogRecord(T0 + timedelta(seconds=1), "OOMKilled", "error", {"service": "api"}),
        LogRecord(T0 + timedelta(seconds=2), "OOMKilled", "error", {"service": "worker"}),
    ]
    provider = StaticLogQueryProvider(records)
    got = [
        r async for r in provider.query(LogQuery(expression="OOMKilled", labels={"service": "api"}))
    ]
    assert len(got) == 1
    assert got[0].labels["service"] == "api"


async def test_log_static_respects_limit() -> None:
    records = [LogRecord(T0 + timedelta(seconds=i), f"line {i}", "info", {}) for i in range(5)]
    provider = StaticLogQueryProvider(records)
    got = [r async for r in provider.query(LogQuery(expression="line", limit=2))]
    assert len(got) == 2


# ---------------------------------------------------------------------------
# StaticTraceQueryProvider - filter semantics
# ---------------------------------------------------------------------------


async def test_trace_static_matches_by_trace_id_and_min_duration() -> None:
    spans = [
        Span("t1", "s1", None, "api", "GET /users", T0, timedelta(milliseconds=50), "ok"),
        Span("t1", "s2", "s1", "db", "SELECT", T0, timedelta(milliseconds=200), "ok"),
        Span("t2", "s3", None, "api", "GET /orders", T0, timedelta(milliseconds=500), "error"),
    ]
    provider = StaticTraceQueryProvider(spans)
    got = [
        s
        async for s in provider.query(
            TraceQuery(trace_id="t1", min_duration=timedelta(milliseconds=100))
        )
    ]
    assert [s.span_id for s in got] == ["s2"]


async def test_trace_static_filters_by_service_and_operation() -> None:
    spans = [
        Span("t1", "s1", None, "api", "GET /users", T0, timedelta(milliseconds=50), "ok"),
        Span("t1", "s2", "s1", "api", "GET /orders", T0, timedelta(milliseconds=60), "ok"),
    ]
    provider = StaticTraceQueryProvider(spans)
    got = [s async for s in provider.query(TraceQuery(service="api", operation="GET /users"))]
    assert [s.span_id for s in got] == ["s1"]
