"""AKS node CPU is served by the platform metric, with no workspace, agent or collection rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.metrics_api import AzureMonitorMetricsConfig, AzureMonitorMetricsProvider
from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries
from fdai.shared.providers.metric import MetricProviderError, MetricQuery
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
AKS = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example"
    "/providers/Microsoft.ContainerService/managedClusters/example"
)
METRIC = "node_cpu_usage_percentage"


class Identity(WorkloadIdentity):
    async def get_token(self, audience):
        return IdentityToken(token="fake", expires_at=NOW + timedelta(hours=1), audience=audience)


def provider(handler) -> tuple[AzureMonitorMetricsProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=azure_metrics_api_queries()),
            http_client=client,
            identity=Identity(),
            clock=lambda: NOW,
        ),
        client,
    )


def aks_response(*series):
    return httpx.Response(
        200, json={"value": [{"name": {"value": METRIC}, "timeseries": list(series)}]}
    )


def query(resource_id: str = AKS) -> MetricQuery:
    return MetricQuery(
        "node_cpu_percent", {"resource_id": resource_id}, NOW - timedelta(minutes=5), NOW
    )


async def test_template_asks_for_the_cluster_wide_maximum_of_the_platform_metric() -> None:
    template = azure_metrics_api_queries()["node_cpu_percent"]
    assert template.azure_metric_name == METRIC
    assert template.aggregation == "Maximum"
    assert template.resource_type == "Microsoft.ContainerService/managedClusters"
    assert template.dimension_filters == ()


async def test_real_provider_reads_the_maximum_and_keeps_the_exact_cluster_identity() -> None:
    seen = {}

    def handle(request):
        seen.update(path=request.url.path, params=dict(request.url.params))
        return aks_response(
            {
                "metadatavalues": [],
                "data": [
                    {"timeStamp": (NOW - timedelta(minutes=1)).isoformat(), "maximum": 91.5},
                    {"timeStamp": NOW.isoformat(), "maximum": 64.0},
                ],
            }
        )

    metrics, client = provider(handle)
    async with client:
        assert metrics.serves(query())
        points = [point async for point in metrics.query(query())]
    assert seen["path"].startswith(AKS)
    assert seen["params"]["metricnames"] == METRIC
    assert seen["params"]["aggregation"] == "Maximum"
    assert [point.value for point in points] == [91.5, 64.0]
    assert {point.metric_name for point in points} == {"node_cpu_percent"}
    assert {point.labels["resource_id"] for point in points} == {AKS.casefold()}
    assert all("node" not in point.labels for point in points)


@pytest.mark.parametrize(
    "resource_id",
    [
        AKS.replace("managedClusters", "virtualMachines").replace("ContainerService", "Compute"),
        AKS + "/agentPools/nodepool1",
        "not-an-arm-id",
    ],
)
async def test_only_an_aks_cluster_is_served_so_other_targets_keep_the_logs_route(
    resource_id,
) -> None:
    metrics, client = provider(lambda request: aks_response())
    async with client:
        assert not metrics.serves(query(resource_id))


async def test_a_response_for_another_metric_or_a_split_series_is_rejected() -> None:
    def other_metric(request):
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": {"value": "node_memory_working_set_percentage"},
                        "timeseries": [{"metadatavalues": [], "data": []}],
                    }
                ]
            },
        )

    def split(request):
        node = {"metadatavalues": [{"name": {"value": "node"}, "value": "n1"}], "data": []}
        return aks_response(
            node, {**node, "metadatavalues": [{"name": {"value": "node"}, "value": "n2"}]}
        )

    for handler in (other_metric, split):
        metrics, client = provider(handler)
        async with client:
            with pytest.raises(MetricProviderError):
                [point async for point in metrics.query(query())]


async def test_an_empty_series_is_not_a_healthy_zero() -> None:
    metrics, client = provider(
        lambda request: aks_response(
            {"metadatavalues": [], "data": [{"timeStamp": NOW.isoformat()}]}
        )
    )
    async with client:
        points = [point async for point in metrics.query(query())]
    assert points == []
