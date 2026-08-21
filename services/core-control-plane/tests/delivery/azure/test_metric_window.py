"""Azure metric-window ontology identity binding tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.metric_semantics import (
    MetricAggregation,
    MetricSemanticDefinition,
    MetricWindow,
)
from fdai.delivery.azure.metric_window import (
    AzureMetricWindowConfig,
    AzureMetricWindowProvider,
)

SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
NOW = datetime(2026, 8, 20, tzinfo=UTC)
LOGICAL_ID = (
    "scope-0123456789abcdef/resource-group/example-rg/providers/"
    "microsoft.app/containerapps/service-example-api"
)
ARM_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourcegroups/example-rg/providers/"
    "microsoft.app/containerapps/service-example-api"
)


class _Provider:
    def __init__(self) -> None:
        self.resource_ids: list[str] = []

    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        self.resource_ids.append(resource_id)
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=(MetricSample(timestamp=start, value=1.0),),
            complete=True,
            evidence_refs=("metric-provider:example",),
        )


def _definition() -> MetricSemanticDefinition:
    return MetricSemanticDefinition(
        concept_id="resource.saturation",
        provider_metric="container_app_cpu_nanocores",
        canonical_unit="nanocores",
        aggregation=MetricAggregation.AVERAGE,
        description="CPU consumption of one runtime resource.",
    )


async def test_metric_window_uses_server_subscription_and_restores_logical_identity() -> None:
    provider = _Provider()
    wrapper = AzureMetricWindowProvider(
        provider=provider,
        config=AzureMetricWindowConfig(subscription_id=SUBSCRIPTION_ID),
    )

    result = await wrapper.read(
        definition=_definition(),
        resource_id=LOGICAL_ID,
        start=NOW,
        end=NOW + timedelta(minutes=5),
    )

    assert provider.resource_ids == [ARM_ID]
    assert result.resource_id == LOGICAL_ID
    assert result.complete is True


@pytest.mark.parametrize(
    "resource_id",
    (
        "scope-0123456789abcdef/resource-group/example-rg/providers//invalid",
        "resource-example",
        (
            "/subscriptions/00000000-0000-0000-0000-XXXXXXXXXXXX/resourceGroups/"
            "example-rg/providers/Microsoft.App/containerApps/service-example-api"
        ),
    ),
)
async def test_metric_window_rejects_unbound_or_cross_subscription_identity(
    resource_id: str,
) -> None:
    provider = _Provider()
    wrapper = AzureMetricWindowProvider(
        provider=provider,
        config=AzureMetricWindowConfig(subscription_id=SUBSCRIPTION_ID),
    )

    with pytest.raises(ValueError, match="ontology resource|outside the server subscription"):
        await wrapper.read(
            definition=_definition(),
            resource_id=resource_id,
            start=NOW,
            end=NOW + timedelta(minutes=5),
        )

    assert provider.resource_ids == []
