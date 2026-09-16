from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.azure.model_serving_inventory import (
    MODEL_SERVING_INVENTORY_SOURCE_NAME,
    MODEL_SERVING_METRIC_NAME,
    AzureModelServingInventoryConfig,
    AzureModelServingInventoryEnricher,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.metric import (
    MetricFailureReason,
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    StaticMetricProvider,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactMetadata,
)

NOW = datetime(2026, 9, 16, 2, 0, tzinfo=UTC)
ARM_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/example-rg/providers/Microsoft.CognitiveServices/"
    "accounts/example-account/deployments/example-model"
)


def _resource(*, resource_id: str = "model-1", provider_ref: str | None = ARM_ID) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        type="llm-model-deployment",
        props={"name": "example-model", "properties": {"provisioningState": "Succeeded"}},
        provider_ref=provider_ref,
        last_seen=(NOW - timedelta(minutes=1)).isoformat(),
    )


def _observation(*resources: ResourceRecord, complete: bool = True) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation="generation-1",
        resources=resources or (_resource(),),
        links=(),
        complete=complete,
        recorded_at=NOW,
    )


def _point(
    *,
    value: float,
    at: datetime = NOW - timedelta(minutes=1),
    provider_ref: str = ARM_ID,
    deployment_name: str = "example-model",
    status: str = "200",
) -> MetricPoint:
    return MetricPoint(
        metric_name=MODEL_SERVING_METRIC_NAME,
        at=at,
        value=value,
        labels={
            "resource_id": provider_ref,
            "ModelDeploymentName": deployment_name,
            "StatusCode": status,
        },
    )


class _ErrorProvider:
    def __init__(self, reason: MetricFailureReason) -> None:
        self.reason = reason

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        del query
        raise MetricProviderError("redacted", reason=self.reason)
        yield  # pragma: no cover


class _SlowProvider:
    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        del query
        await asyncio.sleep(1)
        yield _point()  # pragma: no cover


class _PreviousReader:
    def __init__(self, resource: ResourceRecord) -> None:
        self.resource = resource

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        return "generation-0", {
            resource_id: self.resource
            for resource_id in resource_ids
            if resource_id == self.resource.resource_id
        }


async def test_recent_exact_success_records_serving_with_telemetry_provenance() -> None:
    enriched = await AzureModelServingInventoryEnricher(
        provider=StaticMetricProvider([_point(value=2)]),
        clock=lambda: NOW,
    ).enrich(_observation())

    props = enriched.resources[0].props
    assert props["servingState"] == "Serving"
    metadata_root = props[STATE_FACT_METADATA_PROPERTY]
    assert isinstance(metadata_root, Mapping)
    metadata = StateFactMetadata.from_mapping(metadata_root["servingState"])
    assert metadata.authority is StateFactAuthority.TELEMETRY
    assert metadata.source_identity == "azure-monitor-model-serving"
    assert metadata.effective_at == NOW - timedelta(minutes=1)
    assert metadata.synthetic is False
    assert enriched.source_states[0].source == MODEL_SERVING_INVENTORY_SOURCE_NAME
    assert enriched.source_states[0].status == "available"
    assert enriched.source_states[0].coverage == {"observed": 1, "targets": 1}


async def test_zero_or_empty_success_window_stays_explicitly_unobserved() -> None:
    for points in ([], [_point(value=0)]):
        enriched = await AzureModelServingInventoryEnricher(
            provider=StaticMetricProvider(points),
            clock=lambda: NOW,
        ).enrich(_observation())

        props = enriched.resources[0].props
        assert "servingState" not in props
        assert props["state_fact_unavailable_reasons"] == {
            "servingState": "model_serving_not_observed"
        }
        assert enriched.source_states[0].status == "available"
        assert enriched.source_states[0].coverage == {"not_observed": 1, "targets": 1}


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (MetricFailureReason.TIMEOUT, "model_serving_source_unavailable"),
        (MetricFailureReason.INVALID_RESPONSE, "model_serving_response_invalid"),
        (MetricFailureReason.INVALID_QUERY, "model_serving_target_unresolved"),
    ],
)
async def test_metric_failure_is_bounded_per_target(
    failure: MetricFailureReason,
    reason: str,
) -> None:
    enriched = await AzureModelServingInventoryEnricher(
        provider=_ErrorProvider(failure),
        clock=lambda: NOW,
    ).enrich(_observation())

    assert enriched.resources[0].props["state_fact_unavailable_reasons"] == {"servingState": reason}
    assert enriched.source_states[0].status == "unavailable"
    assert enriched.source_states[0].reason == "model_serving_partial"


async def test_prior_serving_fact_is_retained_without_rewriting_its_time() -> None:
    first = await AzureModelServingInventoryEnricher(
        provider=StaticMetricProvider([_point(value=1)]),
        clock=lambda: NOW,
    ).enrich(_observation())
    prior = first.resources[0]

    next_resource = _resource()
    retained = await AzureModelServingInventoryEnricher(
        provider=StaticMetricProvider([]),
        previous_state_reader=_PreviousReader(prior),
        clock=lambda: NOW + timedelta(minutes=6),
    ).enrich(
        PromotedInventoryObservation(
            generation="generation-2",
            resources=(next_resource,),
            links=(),
            complete=True,
            recorded_at=NOW + timedelta(minutes=6),
        )
    )

    assert retained.resources[0].props["servingState"] == "Serving"
    assert (
        retained.resources[0].props[STATE_FACT_METADATA_PROPERTY]["servingState"]
        == prior.props[STATE_FACT_METADATA_PROPERTY]["servingState"]
    )
    assert retained.source_states[0].coverage == {"not_observed": 1, "targets": 1}


async def test_unverified_metric_identity_never_records_serving() -> None:
    enriched = await AzureModelServingInventoryEnricher(
        provider=StaticMetricProvider([_point(value=1, deployment_name="another-model")]),
        clock=lambda: NOW,
    ).enrich(_observation())

    assert enriched.resources[0].props["state_fact_unavailable_reasons"] == {
        "servingState": "model_serving_response_invalid"
    }


async def test_target_limit_and_total_deadline_do_not_block_promotion() -> None:
    resources = (
        _resource(resource_id="model-1"),
        _resource(
            resource_id="model-2",
            provider_ref=ARM_ID.replace("example-model", "example-model-2"),
        ),
    )
    limited = await AzureModelServingInventoryEnricher(
        provider=StaticMetricProvider([_point(value=1)]),
        config=AzureModelServingInventoryConfig(max_targets=1),
        clock=lambda: NOW,
    ).enrich(_observation(*resources))
    assert limited.resources[1].props["state_fact_unavailable_reasons"] == {
        "servingState": "model_serving_target_limit"
    }

    timed_out = await AzureModelServingInventoryEnricher(
        provider=_SlowProvider(),
        config=AzureModelServingInventoryConfig(total_timeout_seconds=0.1),
        clock=lambda: NOW,
    ).enrich(_observation())
    assert timed_out.resources[0].props["state_fact_unavailable_reasons"] == {
        "servingState": "model_serving_source_unavailable"
    }
    assert timed_out.source_states[0].reason == "model_serving_timeout"


def test_config_rejects_unbounded_values() -> None:
    with pytest.raises(ValueError, match="lookback"):
        AzureModelServingInventoryConfig(lookback_seconds=59)
    with pytest.raises(ValueError, match="freshness"):
        AzureModelServingInventoryConfig(
            lookback_seconds=300,
            freshness_ceiling_seconds=299,
        )
    with pytest.raises(ValueError, match="max_concurrency"):
        AzureModelServingInventoryConfig(max_concurrency=9)
