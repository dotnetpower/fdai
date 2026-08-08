"""httpx-mocked tests for the Prometheus metric adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.prometheus.metric import (
    PrometheusMetricConfig,
    PrometheusMetricProvider,
)
from fdai.shared.providers.metric import MetricProviderError, MetricQuery

_METRIC = "http.server.request.rate"


def _config(**overrides: object) -> PrometheusMetricConfig:
    base = dict(
        base_url="https://prom.local",
        queries={_METRIC: "rate(http_requests_total[1m])"},
    )
    base.update(overrides)
    return PrometheusMetricConfig(**base)  # type: ignore[arg-type]


def _provider(
    handler, cfg: PrometheusMetricConfig | None = None
) -> tuple[PrometheusMetricProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PrometheusMetricProvider(config=cfg or _config(), http_client=client), client


@pytest.mark.asyncio
async def test_range_query_maps_matrix_samples() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {"__name__": "http_requests_total", "pod": "a"},
                            "values": [[1_700_000_060, "2.0"], [1_700_000_000, "1.0"]],
                        }
                    ],
                },
            },
        )

    provider, client = _provider(handler)
    since = datetime(2026, 7, 10, tzinfo=UTC)
    until = since + timedelta(minutes=5)
    try:
        points = [
            p
            async for p in provider.query(
                MetricQuery(metric_name=_METRIC, since=since, until=until)
            )
        ]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [1.0, 2.0]  # sorted chronologically
    assert points[0].labels == {"pod": "a"}
    assert "/api/v1/query_range" in str(captured[0].url)


@pytest.mark.asyncio
async def test_instant_query_when_no_window() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {"pod": "b"}, "value": [1_700_000_000, "7.0"]}],
                },
            },
        )

    provider, client = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert len(points) == 1
    assert points[0].value == 7.0
    assert str(captured[0].url).endswith("/api/v1/query")


@pytest.mark.asyncio
async def test_labels_filter_in_memory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {"pod": "a"}, "value": [1_700_000_000, "1.0"]},
                        {"metric": {"pod": "b"}, "value": [1_700_000_000, "2.0"]},
                    ],
                },
            },
        )

    provider, client = _provider(handler)
    try:
        points = [
            p async for p in provider.query(MetricQuery(metric_name=_METRIC, labels={"pod": "b"}))
        ]
    finally:
        await client.aclose()

    assert len(points) == 1
    assert points[0].labels == {"pod": "b"}


@pytest.mark.asyncio
async def test_non_success_status_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "error": "bad query"})

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="status"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="HTTP 502"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unknown_metric_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={"status": "success", "data": {}})

    provider, client = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="no PromQL query"):
            _ = [p async for p in provider.query(MetricQuery(metric_name="nope"))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_non_finite_samples_are_skipped() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {"pod": "a"},
                            "values": [
                                [1_700_000_000, "NaN"],
                                [1_700_000_060, "3.0"],
                                [1_700_000_120, "+Inf"],
                            ],
                        }
                    ],
                },
            },
        )

    provider, client = _provider(handler)
    since = datetime(2026, 7, 10, tzinfo=UTC)
    try:
        points = [
            p
            async for p in provider.query(
                MetricQuery(metric_name=_METRIC, since=since, until=since + timedelta(minutes=5))
            )
        ]
    finally:
        await client.aclose()

    # NaN and +Inf dropped; only the finite sample survives.
    assert [p.value for p in points] == [3.0]


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="base_url"):
        PrometheusMetricConfig(base_url="", queries={})
    with pytest.raises(ValueError, match="step_seconds"):
        PrometheusMetricConfig(base_url="u", queries={}, step_seconds=0)
    with pytest.raises(ValueError, match="no WorkloadIdentity"):
        PrometheusMetricProvider(
            config=PrometheusMetricConfig(base_url="u", queries={}, audience="api://x"),
            http_client=httpx.AsyncClient(),
        )
