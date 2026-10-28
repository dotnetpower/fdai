"""The additive VMSS template executes through the real metrics-provider seam."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.core.investigation.host_cpu import METRIC_HOST_CPU_PERCENT, METRIC_VMSS_CPU_PERCENT
from fdai.delivery.azure.host_cpu_queries import vmss_cpu_metric_templates
from fdai.delivery.azure.metrics_api import AzureMonitorMetricsConfig, AzureMonitorMetricsProvider
from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries
from fdai.shared.providers.metric import MetricQuery
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ARM = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example"
    "/providers/Microsoft.Compute/virtualMachineScaleSets/example"
)


class Identity(WorkloadIdentity):
    async def get_token(self, audience):
        return IdentityToken(token="fake", expires_at=NOW + timedelta(hours=1), audience=audience)


async def test_registered_vmss_template_is_exact_and_preserves_existing_vm_and_mysql() -> None:
    existing = azure_metrics_api_queries()
    templates = {**existing, **vmss_cpu_metric_templates()}
    assert templates[METRIC_HOST_CPU_PERCENT] is existing[METRIC_HOST_CPU_PERCENT]
    assert templates["cpu_percent"] is existing["cpu_percent"]
    assert templates[METRIC_VMSS_CPU_PERCENT].azure_metric_name == "Percentage CPU"

    def handle(request):
        assert request.url.path.startswith(ARM)
        assert request.url.params["metricnames"] == "Percentage CPU"
        assert request.url.params["aggregation"] == "Average"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": {"value": "Percentage CPU"},
                        "timeseries": [
                            {
                                "metadatavalues": [],
                                "data": [{"timeStamp": NOW.isoformat(), "average": 95.0}],
                            }
                        ],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = AzureMonitorMetricsProvider(
            config=AzureMonitorMetricsConfig(templates=templates),
            http_client=client,
            identity=Identity(),
            clock=lambda: NOW,
        )
        query = MetricQuery(
            METRIC_VMSS_CPU_PERCENT,
            {"resource_id": ARM},
            NOW - timedelta(minutes=5),
            NOW,
        )
        assert provider.serves(query)
        assert not provider.serves(
            MetricQuery(METRIC_VMSS_CPU_PERCENT, {"resource_id": ARM + "/virtualMachines/0"})
        )
        assert not provider.serves(MetricQuery(METRIC_HOST_CPU_PERCENT, {"resource_id": ARM}))
        points = [point async for point in provider.query(query)]
    assert len(points) == 1
    assert points[0].metric_name == METRIC_VMSS_CPU_PERCENT
    assert points[0].labels["resource_id"] == ARM.casefold()
    assert points[0].value == 95.0
    with pytest.raises(TypeError):
        vmss_cpu_metric_templates()["cpu_percent"] = templates[METRIC_VMSS_CPU_PERCENT]
