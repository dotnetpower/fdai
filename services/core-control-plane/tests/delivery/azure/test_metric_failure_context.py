"""Safe diagnostics at both Azure transports and the mapped identity boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import httpx
import pytest
from fdai.delivery.analyzer_metric_provider import AnalyzerMetricProvider
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.azure.metric_logs import (
    AzureMonitorLogsConfig,
    AzureMonitorLogsMetricProvider,
    MetricKqlTemplate,
)
from fdai.delivery.azure.metrics_api import (
    AzureMonitorMetricsConfig,
    AzureMonitorMetricsProvider,
    MetricsApiTemplate,
)
from fdai.shared.providers.metric import (
    MetricFailureReason,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.workload_identity import IdentityToken

Kind = Literal["logs", "metrics"]
_RESOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/example-rg/providers/Microsoft.Compute/virtualMachines/example-vm"
)
_PRIVATE = "https://example.com/private-provider-payload"
_AT = "2026-09-15T00:01:00Z"


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="fake",
            audience=audience,
            expires_at=datetime(2026, 9, 16, tzinfo=UTC),
        )


def _provider(
    kind: Kind,
    client: httpx.AsyncClient,
    *,
    mapped: bool,
    max_bytes: int = 10_000,
    max_samples: int = 10,
) -> MetricProvider:
    provider: MetricProvider
    if kind == "logs":
        provider = AzureMonitorLogsMetricProvider(
            config=AzureMonitorLogsConfig(
                workspace_id="00000000-0000-0000-0000-000000000000",
                queries={
                    "example.metric": MetricKqlTemplate(
                        kql="ExampleTable | project TimeGenerated, v, resource_id",
                        value_column="v",
                        label_columns=("resource_id",),
                    )
                },
                max_response_bytes=max_bytes,
                max_rows=max_samples,
            ),
            identity=_Identity(),
            http_client=client,
        )
    else:
        provider = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(
                templates={
                    "example.metric": MetricsApiTemplate(
                        azure_metric_name="ExampleMetric", aggregation="Average"
                    )
                },
                max_response_bytes=max_bytes,
                max_points=max_samples,
            ),
            identity=_Identity(),
            http_client=client,
        )
    if mapped:
        return AnalyzerMetricProvider(
            provider,
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-logical",
                    resource_kind="vm",
                    provider_query_ref=_RESOURCE,
                ),
            ),
            normalize_provider_ref=str.casefold,
        )
    return provider


def _query(mapped: bool) -> MetricQuery:
    return MetricQuery(
        metric_name="example.metric",
        labels={"resource_id": "resource-logical" if mapped else _RESOURCE.lower()},
    )


def _payload(kind: Kind, rows: list[tuple[object, object]]) -> dict[str, object]:
    if kind == "logs":
        return {
            "tables": [
                {
                    "columns": [
                        {"name": "TimeGenerated"},
                        {"name": "v"},
                        {"name": "resource_id"},
                    ],
                    "rows": [[at, value, _RESOURCE.lower()] for at, value in rows],
                }
            ]
        }
    return {
        "value": [
            {"timeseries": [{"data": [{"timeStamp": at, "average": value} for at, value in rows]}]}
        ]
    }


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize(
    ("error_type", "reason"),
    [
        (httpx.ReadTimeout, MetricFailureReason.TIMEOUT),
        (httpx.ConnectTimeout, MetricFailureReason.TIMEOUT),
        (httpx.WriteTimeout, MetricFailureReason.TIMEOUT),
        (httpx.PoolTimeout, MetricFailureReason.TIMEOUT),
        (httpx.ConnectError, MetricFailureReason.TRANSPORT_ERROR),
        (httpx.RemoteProtocolError, MetricFailureReason.TRANSPORT_ERROR),
    ],
)
async def test_transport_failure_is_classified_without_retry_or_private_text(
    kind: Kind, mapped: bool, error_type: type[httpx.HTTPError], reason: MetricFailureReason
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_type(_PRIVATE, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(kind, client, mapped=mapped)
        with pytest.raises(MetricProviderError) as caught:
            _ = [point async for point in provider.query(_query(mapped))]

    assert calls == 1
    assert caught.value.reason is reason
    assert caught.value.http_status is None
    assert _PRIVATE not in str(caught.value)
    assert _RESOURCE not in str(caught.value)
    if mapped:
        assert f"reason={reason.value}" in str(caught.value)
        assert caught.value.__cause__ is caught.value.__context__ is None


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("status", [401, 403, 429, 503])
@pytest.mark.parametrize("raise_status", [False, True])
async def test_http_failure_retains_only_observed_status(
    kind: Kind, mapped: bool, status: int, raise_status: bool
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        response = httpx.Response(status, text=_PRIVATE, request=request)
        if raise_status:
            response.raise_for_status()
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(kind, client, mapped=mapped)
        with pytest.raises(MetricProviderError) as caught:
            _ = [point async for point in provider.query(_query(mapped))]

    assert calls == 1
    assert caught.value.reason is MetricFailureReason.HTTP_ERROR
    assert caught.value.http_status == status
    assert _PRIVATE not in str(caught.value)
    assert _RESOURCE not in str(caught.value)
    if mapped:
        assert f"reason=http_error, http_status={status}" in str(caught.value)
        assert caught.value.__cause__ is caught.value.__context__ is None


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize(
    "response",
    [
        lambda kind: httpx.Response(200, text=_PRIVATE),
        lambda kind: httpx.Response(200, json=[]),
        lambda kind: httpx.Response(200, json={}),
        lambda kind: httpx.Response(200, json=_payload(kind, [(_PRIVATE, 1)])),
        lambda kind: httpx.Response(200, json=_payload(kind, [(_AT, _PRIVATE)])),
        lambda kind: httpx.Response(200, json=_payload(kind, [(_AT, True)])),
        lambda kind: httpx.Response(200, json=_payload(kind, [(_AT, "NaN")])),
    ],
    ids=["non-json", "envelope", "missing-series", "timestamp", "value", "boolean", "non-finite"],
)
async def test_malformed_response_remains_failed_not_empty(
    kind: Kind, mapped: bool, response: Callable[[Kind], httpx.Response]
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response(kind))) as client:
        provider = _provider(kind, client, mapped=mapped)
        with pytest.raises(MetricProviderError) as caught:
            _ = [point async for point in provider.query(_query(mapped))]

    assert caught.value.reason is MetricFailureReason.INVALID_RESPONSE
    assert caught.value.http_status is None
    assert _PRIVATE not in str(caught.value)
    if mapped:
        assert "reason=invalid_response" in str(caught.value)
        assert caught.value.__cause__ is caught.value.__context__ is None


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize(("max_bytes", "max_samples"), [(32, 10), (10_000, 1)])
async def test_response_limits_have_distinct_context(
    kind: Kind, mapped: bool, max_bytes: int, max_samples: int
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_payload(kind, [(_AT, 1), (_AT, 2)]))
        )
    ) as client:
        provider = _provider(
            kind, client, mapped=mapped, max_bytes=max_bytes, max_samples=max_samples
        )
        with pytest.raises(MetricProviderError) as caught:
            _ = [point async for point in provider.query(_query(mapped))]

    assert caught.value.reason is MetricFailureReason.RESPONSE_LIMIT
    assert caught.value.http_status is None


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
async def test_valid_empty_response_stays_empty(kind: Kind, mapped: bool) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload(kind, [])))
    ) as client:
        provider = _provider(kind, client, mapped=mapped)
        assert [point async for point in provider.query(_query(mapped))] == []


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
async def test_successful_sample_preserves_query_identity(kind: Kind, mapped: bool) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_payload(kind, [(_AT, 3)]))
        )
    ) as client:
        provider = _provider(kind, client, mapped=mapped)
        query = _query(mapped)
        points = [point async for point in provider.query(query)]

    assert len(points) == 1
    assert points[0].value == 3
    assert points[0].labels == query.labels


async def test_metric_level_failure_is_not_inferred_to_be_an_http_failure() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"value": [{"errorCode": _PRIVATE}]})
        )
    ) as client:
        provider = _provider("metrics", client, mapped=True)
        with pytest.raises(MetricProviderError) as caught:
            _ = [point async for point in provider.query(_query(True))]

    assert caught.value.reason is MetricFailureReason.PROVIDER_ERROR
    assert caught.value.http_status is None
    assert _PRIVATE not in str(caught.value)


@pytest.mark.parametrize("kind", ["logs", "metrics"])
@pytest.mark.parametrize("mapped", [False, True])
async def test_invalid_query_is_classified_before_transport(kind: Kind, mapped: bool) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("an unconfigured metric must not reach the transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(kind, client, mapped=mapped)
        with pytest.raises(MetricProviderError) as caught:
            _ = [
                point
                async for point in provider.query(
                    MetricQuery(metric_name="unconfigured", labels=_query(mapped).labels)
                )
            ]

    assert caught.value.reason is MetricFailureReason.INVALID_QUERY
    assert caught.value.http_status is None
