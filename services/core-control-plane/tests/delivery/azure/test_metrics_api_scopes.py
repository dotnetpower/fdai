"""Native gateway and model metrics preserve exact target and dimension scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fdai.delivery.azure.demo_queries import (
    METRIC_BACKEND_FIRST_BYTE_MS,
    METRIC_HEALTHY_HOST_COUNT,
    sre_demo_analyzer_queries,
)
from fdai.delivery.azure.metric_window import AzureMetricWindowConfig, AzureMetricWindowProvider
from fdai.delivery.azure.metrics_api import (
    AzureMonitorMetricsConfig,
    AzureMonitorMetricsProvider,
    MetricsApiDimensionFilter,
    MetricsApiTemplate,
)
from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries
from fdai.delivery.metric_window import ProviderMetricWindowReader
from fdai.runtime.metric_semantic_catalog import load_metric_semantic_registry
from fdai.shared.providers.metric import MetricProviderError, MetricQuery
from fdai.shared.providers.workload_identity import IdentityToken

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
ROOT = Path(__file__).resolve().parents[5]
ACCOUNT = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example-rg"
    "/providers/Microsoft.CognitiveServices/accounts/example-account"
)
DEPLOYMENT = f"{ACCOUNT}/deployments/example-model"
APIM = ACCOUNT.replace("Microsoft.CognitiveServices/accounts", "Microsoft.ApiManagement/service")
NOW = datetime(2026, 8, 21, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(token="fake", expires_at=NOW + timedelta(days=1), audience=audience)


def _payload(metric: str, dimensions: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "value": [
            {
                "name": {"value": metric},
                "timeseries": [
                    {
                        "metadatavalues": [
                            {"name": {"value": name}, "value": value}
                            for name, value in (dimensions or {}).items()
                        ],
                        "data": [
                            {"timeStamp": NOW.isoformat(), "total": 0, "average": 12.0},
                            {"timeStamp": (NOW + timedelta(minutes=1)).isoformat()},
                        ],
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("StatusCode or true", "429"),
        ("StatusCode", "429' or StatusCode eq '500"),
        ("StatusCode", "*"),
        ("StatusCode", "x" * 129),
        ("resource_id", "example"),
    ],
)
def test_dimension_filters_reject_fragments_and_unbounded_literals(name: str, value: str) -> None:
    with pytest.raises(ValueError, match="metric dimension"):
        MetricsApiDimensionFilter(name, value)


def test_templates_preserve_legacy_constructor_and_bound_filter_scope() -> None:
    assert MetricsApiTemplate("Requests", "Total", "PT1M").dimension_filters == ()
    with pytest.raises(ValueError, match="unique names"):
        MetricsApiTemplate(
            "Requests",
            "Total",
            dimension_filters=(
                MetricsApiDimensionFilter("StatusCode", "429"),
                MetricsApiDimensionFilter("statuscode", "500"),
            ),
        )
    with pytest.raises(ValueError, match="at most four"):
        MetricsApiTemplate(
            "Requests",
            "Total",
            dimension_filters=tuple(MetricsApiDimensionFilter(f"Dim{i}", "x") for i in range(5)),
        )
    with pytest.raises(ValueError, match="deployment scope"):
        MetricsApiTemplate("Requests", "Total", deployment_scope=True)


@pytest.mark.parametrize("status", ["429", "500", "503"])
@pytest.mark.parametrize("backend", [False, True])
async def test_apim_status_counts_use_exact_response_dimension(status: str, backend: bool) -> None:
    concept = f"api_gateway.{'backend.' if backend else ''}response.{status}.count"
    dimension = "BackendResponseCode" if backend else "GatewayResponseCode"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.params["metricnames"] == "Requests"
        assert request.url.params["aggregation"] == "Total"
        assert request.url.params["$filter"] == f"{dimension} eq '{status}'"
        assert request.url.params["ValidateDimensions"] == "true"
        return httpx.Response(200, json=_payload("Requests", {dimension: status}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        points = [
            point
            async for point in provider.query(
                MetricQuery(metric_name=concept, labels={"resource_id": APIM}, since=NOW)
            )
        ]
    assert len(seen) == 1
    assert [point.value for point in points] == [0.0]
    assert points[0].labels == {"resource_id": APIM.lower(), dimension: status}


async def test_deployment_metric_window_queries_account_without_widening_child() -> None:
    definition = load_metric_semantic_registry(
        ROOT / "rule-catalog/vocabulary/metric-semantics.yaml"
    ).resolve("model.response.429.count")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.casefold() == (
            f"{ACCOUNT}/providers/Microsoft.Insights/metrics".casefold()
        )
        assert request.url.params["$filter"] == (
            "StatusCode eq '429' and ModelDeploymentName eq 'example-model'"
        )
        return httpx.Response(
            200,
            json=_payload(
                "AzureOpenAIRequests", {"StatusCode": "429", "ModelDeploymentName": "example-model"}
            ),
        )

    logical_id = (
        "scope-0123456789abcdef/resource-group/example-rg/providers/"
        "microsoft.cognitiveservices/accounts/example-account/deployments/example-model"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        native = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        reader = AzureMetricWindowProvider(
            provider=ProviderMetricWindowReader(provider=native),
            config=AzureMetricWindowConfig(subscription_id=SUBSCRIPTION),
        )
        window = await reader.read(
            definition=definition,
            resource_id=logical_id,
            start=NOW,
            end=NOW + timedelta(minutes=5),
        )
    assert window.resource_id == logical_id
    assert window.concept_id == definition.concept_id
    assert window.complete is True
    assert tuple(sample.value for sample in window.samples) == (0.0,)


@pytest.mark.parametrize(
    "concept",
    ["gateway.total_time", "api_gateway.duration", "model.request.count", "model.token.count"],
)
async def test_canonical_account_metrics_are_unsplit_metric_windows(concept: str) -> None:
    definition = load_metric_semantic_registry(
        ROOT / "rule-catalog/vocabulary/metric-semantics.yaml"
    ).resolve(concept)
    template = azure_metrics_api_queries()[definition.provider_metric]
    resource_id = ACCOUNT.replace(
        "Microsoft.CognitiveServices/accounts", template.resource_type or ""
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "$filter" not in request.url.params
        assert request.url.path.casefold().startswith(resource_id.casefold() + "/providers/")
        return httpx.Response(200, json=_payload(template.azure_metric_name))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        native = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        window = await ProviderMetricWindowReader(provider=native).read(
            definition=definition,
            resource_id=resource_id.lower(),
            start=NOW,
            end=NOW + timedelta(minutes=5),
        )
    assert window.complete is True
    assert len(window.samples) == 1
    assert window.samples[0].value == (0.0 if template.aggregation == "Total" else 12.0)


async def test_labels_cannot_supply_or_override_odata_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["$filter"] == "GatewayResponseCode eq '500'"
        return httpx.Response(200, json=_payload("Requests", {"GatewayResponseCode": "500"}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        native = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        points = [
            point
            async for point in native.query(
                MetricQuery(
                    metric_name="api_gateway.response.500.count",
                    labels={"resource_id": APIM, "$filter": "GatewayResponseCode eq '*'"},
                    since=NOW,
                )
            )
        ]
    assert points == []


async def test_empty_deployment_series_is_missing_not_zero() -> None:
    definition = load_metric_semantic_registry(
        ROOT / "rule-catalog/vocabulary/metric-semantics.yaml"
    ).resolve("model.response.503.count")
    payload = _payload("AzureOpenAIRequests")
    payload["value"][0]["timeseries"] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        native = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        window = await ProviderMetricWindowReader(provider=native).read(
            definition=definition,
            resource_id=DEPLOYMENT.lower(),
            start=NOW,
            end=NOW + timedelta(minutes=5),
        )
    assert window.complete is False
    assert window.samples == ()
    assert window.missing_reason == "provider_gap"


@pytest.mark.parametrize(
    "resource_id",
    [
        APIM,
        f"{ACCOUNT}/deployments",
        f"{DEPLOYMENT}/versions/example",
        f"{ACCOUNT}/other/example",
        f"{ACCOUNT}/deployments/a' or true",
        f"{ACCOUNT}/deployments/..",
        f"{ACCOUNT}//deployments/example-model",
    ],
)
async def test_model_templates_reject_incompatible_or_malformed_scope_before_io(
    resource_id: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid scope MUST NOT call the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        with pytest.raises(MetricProviderError, match="resource type"):
            _ = [
                point
                async for point in provider.query(
                    MetricQuery(
                        metric_name="model.request.count", labels={"resource_id": resource_id}
                    )
                )
            ]


@pytest.mark.parametrize(
    "dimensions",
    [
        {},
        {"ModelDeploymentName": "other-model"},
        {"ModelDeploymentName": "example-model", "StatusCode": "429"},
        {"resource_id": ACCOUNT.lower()},
    ],
)
async def test_deployment_rejects_absent_wrong_or_extra_returned_dimensions(
    dimensions: dict[str, str],
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_payload("AzureOpenAIRequests", dimensions))
        )
    ) as client:
        provider = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        with pytest.raises(MetricProviderError, match="dimensions"):
            _ = [
                point
                async for point in provider.query(
                    MetricQuery(
                        metric_name="model.request.count", labels={"resource_id": DEPLOYMENT}
                    )
                )
            ]


@pytest.mark.parametrize(
    "defect",
    ["metric", "resource", "split", "duplicate_dimension", "duplicate_point", "boolean", "error"],
)
async def test_scoped_provider_rejects_unverified_response_identity(defect: str) -> None:
    payload = _payload("AzureOpenAIRequests", {"ModelDeploymentName": "example-model"})
    entry = payload["value"][0]
    if defect == "metric":
        entry["name"]["value"] = "TokenTransaction"
    elif defect == "resource":
        entry["id"] = f"{APIM}/providers/Microsoft.Insights/metrics/AzureOpenAIRequests"
    elif defect == "split":
        entry["timeseries"] *= 2
    elif defect == "duplicate_dimension":
        entry["timeseries"][0]["metadatavalues"] *= 2
    elif defect == "duplicate_point":
        entry["timeseries"][0]["data"] *= 2
    elif defect == "boolean":
        entry["timeseries"][0]["data"][0]["total"] = False
    else:
        entry["errorCode"] = "InvalidSamplingType"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        provider = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=_Identity(),
        )
        with pytest.raises(MetricProviderError):
            _ = [
                point
                async for point in provider.query(
                    MetricQuery(
                        metric_name="model.request.count", labels={"resource_id": DEPLOYMENT}
                    )
                )
            ]


def test_gateway_fallbacks_keep_first_byte_and_supported_host_aggregation() -> None:
    native = azure_metrics_api_queries()
    fallback = sre_demo_analyzer_queries()
    first_byte = native[METRIC_BACKEND_FIRST_BYTE_MS]
    assert first_byte.azure_metric_name == "BackendFirstByteResponseTime"
    assert first_byte.aggregation == "Average"
    assert "BackendFirstByteResponseTime" in fallback[METRIC_BACKEND_FIRST_BYTE_MS].kql
    assert "timeTaken" not in fallback[METRIC_BACKEND_FIRST_BYTE_MS].kql
    assert native[METRIC_HEALTHY_HOST_COUNT].aggregation == "Average"
    assert "avg(Average)" in fallback[METRIC_HEALTHY_HOST_COUNT].kql
    assert "Minimum" not in fallback[METRIC_HEALTHY_HOST_COUNT].kql
