"""Tests for the Azure Monitor Metrics REST API adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.metrics_api import (
    AzureMonitorMetricsConfig,
    AzureMonitorMetricsProvider,
    MetricsApiTemplate,
)
from fdai.shared.providers.metric import MetricProviderError, MetricQuery
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="fake",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _config(**overrides: object) -> AzureMonitorMetricsConfig:
    base: dict[str, object] = {
        "templates": {
            "cpu_percent": MetricsApiTemplate(
                azure_metric_name="cpu_percent",
                aggregation="Average",
            ),
        },
    }
    base.update(overrides)
    return AzureMonitorMetricsConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_rejects_empty_templates() -> None:
    with pytest.raises(ValueError, match="templates MUST be non-empty"):
        AzureMonitorMetricsConfig(templates={})


def test_config_rejects_plaintext_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint MUST use https://"):
        _config(endpoint="http://management.azure.com")


def test_template_rejects_bad_aggregation() -> None:
    with pytest.raises(ValueError, match="aggregation MUST be one of"):
        MetricsApiTemplate(azure_metric_name="cpu_percent", aggregation="Bogus")


def test_template_rejects_non_iso_interval() -> None:
    with pytest.raises(ValueError, match="interval MUST be an ISO 8601"):
        MetricsApiTemplate(
            azure_metric_name="cpu_percent",
            aggregation="Average",
            interval="1m",
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


_ARM_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/example-rg/providers/Microsoft.DBforMySQL"
    "/flexibleServers/example-mysql"
)


async def test_query_dispatches_and_parses_timeseries() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        # ARM id encoded but leading slash + inner slashes preserved.
        assert str(request.url).startswith("https://management.azure.com" + _ARM_ID) or str(
            request.url
        ).startswith("https://management.azure.com/subscriptions/")
        # Ask for the mapped Azure metric name, not the CSP-neutral one.
        assert "metricnames=cpu_percent" in str(request.url)
        assert "aggregation=Average" in str(request.url)
        assert request.headers["Authorization"] == "Bearer fake"
        payload = {
            "value": [
                {
                    "name": {"value": "cpu_percent"},
                    "timeseries": [
                        {
                            "metadatavalues": [{"name": {"value": "shard"}, "value": "primary"}],
                            "data": [
                                {
                                    "timeStamp": "2026-07-13T00:01:00Z",
                                    "average": 42.5,
                                },
                                {
                                    "timeStamp": "2026-07-13T00:02:00Z",
                                    "average": 55.0,
                                },
                            ],
                        }
                    ],
                }
            ]
        }
        return httpx.Response(200, content=json.dumps(payload))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AzureMonitorMetricsProvider(
        config=_config(),
        http_client=http,
        identity=_StaticIdentity(),
    )
    points = [
        p
        async for p in provider.query(
            MetricQuery(
                metric_name="cpu_percent",
                labels={"resource_id": _ARM_ID},
                since=datetime(2026, 7, 13, 0, 0, tzinfo=UTC),
                until=datetime(2026, 7, 13, 0, 5, tzinfo=UTC),
            )
        )
    ]
    assert len(seen_requests) == 1
    assert [p.value for p in points] == [42.5, 55.0]
    # metadata folded onto every point + resource_id normalized lowercase.
    assert points[0].labels["resource_id"] == _ARM_ID.lower()
    assert points[0].labels["shard"] == "primary"


async def test_query_skips_bins_with_no_aggregate() -> None:
    """The Metrics API returns a bin with a timeStamp but no aggregate
    key when there was no data in that bucket - MUST NOT be emitted as
    a phantom zero."""

    def handler(_request: httpx.Request) -> httpx.Response:
        payload = {
            "value": [
                {
                    "name": {"value": "cpu_percent"},
                    "timeseries": [
                        {
                            "data": [
                                {"timeStamp": "2026-07-13T00:01:00Z", "average": 42.5},
                                {"timeStamp": "2026-07-13T00:02:00Z"},  # no data
                                {"timeStamp": "2026-07-13T00:03:00Z", "average": 60.0},
                            ]
                        }
                    ],
                }
            ]
        }
        return httpx.Response(200, content=json.dumps(payload))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AzureMonitorMetricsProvider(
        config=_config(), http_client=http, identity=_StaticIdentity()
    )
    points = [
        p
        async for p in provider.query(
            MetricQuery(metric_name="cpu_percent", labels={"resource_id": _ARM_ID})
        )
    ]
    assert [p.value for p in points] == [42.5, 60.0]


# ---------------------------------------------------------------------------
# Fail-closed on unknown / bad shape / HTTP errors
# ---------------------------------------------------------------------------


async def test_missing_template_fails_closed() -> None:
    http = httpx.AsyncClient()
    provider = AzureMonitorMetricsProvider(
        config=_config(), http_client=http, identity=_StaticIdentity()
    )
    with pytest.raises(MetricProviderError, match="no Metrics API template"):
        async for _ in provider.query(
            MetricQuery(metric_name="unknown", labels={"resource_id": _ARM_ID})
        ):
            pass


async def test_missing_resource_id_fails_closed() -> None:
    http = httpx.AsyncClient()
    provider = AzureMonitorMetricsProvider(
        config=_config(), http_client=http, identity=_StaticIdentity()
    )
    with pytest.raises(MetricProviderError, match="``resource_id`` label"):
        async for _ in provider.query(MetricQuery(metric_name="cpu_percent")):
            pass


async def test_http_error_fails_closed() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error":"throttled"}')

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AzureMonitorMetricsProvider(
        config=_config(), http_client=http, identity=_StaticIdentity()
    )
    with pytest.raises(MetricProviderError, match="HTTP 429"):
        async for _ in provider.query(
            MetricQuery(metric_name="cpu_percent", labels={"resource_id": _ARM_ID})
        ):
            pass


async def test_non_finite_value_fails_closed() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "value": [
                        {
                            "name": {"value": "cpu_percent"},
                            "timeseries": [
                                {
                                    "data": [
                                        {
                                            "timeStamp": "2026-07-13T00:01:00Z",
                                            "average": "Infinity",
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                }
            ),
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AzureMonitorMetricsProvider(
        config=_config(), http_client=http, identity=_StaticIdentity()
    )
    with pytest.raises(MetricProviderError, match="non-finite"):
        async for _ in provider.query(
            MetricQuery(metric_name="cpu_percent", labels={"resource_id": _ARM_ID})
        ):
            pass


async def test_over_max_points_fails_closed() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "value": [
                        {
                            "name": {"value": "cpu_percent"},
                            "timeseries": [
                                {
                                    "data": [
                                        {
                                            "timeStamp": f"2026-07-13T00:00:{i:02d}Z",
                                            "average": 1.0,
                                        }
                                        for i in range(6)
                                    ]
                                }
                            ],
                        }
                    ]
                }
            ),
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AzureMonitorMetricsProvider(
        config=_config(max_points=3),
        http_client=http,
        identity=_StaticIdentity(),
    )
    with pytest.raises(MetricProviderError, match="more than 3 points"):
        async for _ in provider.query(
            MetricQuery(metric_name="cpu_percent", labels={"resource_id": _ARM_ID})
        ):
            pass


async def test_shipped_azure_metrics_api_queries_are_valid() -> None:
    """Coverage: the 4 shipped templates all pass their post-init
    validators, and their metric-names correspond to a real analyzer
    metric so a lookup miss never occurs at runtime."""
    from fdai.delivery.azure.demo_queries import sre_demo_analyzer_queries
    from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries

    shipped = azure_metrics_api_queries()
    assert set(shipped).issubset(set(sre_demo_analyzer_queries())), (
        "every Metrics API template MUST also be an analyzer metric"
    )
    # Every template already validated on construction; assert the
    # shipped set is what we advertise (4 direct-mapped metrics).
    assert len(shipped) == 4
