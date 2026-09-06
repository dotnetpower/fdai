from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fdai.delivery.azure.resource_health_inventory import (
    AzureResourceHealthInventoryConfig,
    AzureResourceHealthInventoryEnricher,
)
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
OBSERVED = datetime(2026, 9, 6, 1, 0, tzinfo=UTC)
COMPLETED = datetime(2026, 9, 6, 1, 1, tzinfo=UTC)


def _resource(resource_type: str = "log-workspace") -> ResourceRecord:
    return ResourceRecord(
        resource_id=f"scope-example/resource-group/example/providers/{resource_type}/one",
        type=resource_type,
        props={"name": "one", "properties": {"provisioningState": "Succeeded"}},
        provider_ref=(
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.OperationalInsights/workspaces/one"
        ),
        last_seen=OBSERVED.isoformat(),
    )


def _resource_with_health(
    state: str,
    *,
    observed_at: datetime,
) -> ResourceRecord:
    resource = _resource()
    evidence_ref = "azure-resource-health:sha256:" + "2" * 64
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="azure-resource-health",
        source_revision=evidence_ref,
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(evidence_ref,),
    )
    return ResourceRecord(
        resource_id=resource.resource_id,
        type=resource.type,
        props={
            **resource.props,
            "availabilityState": state,
            "availabilityReasonKind": "status_only",
            "state_fact_metadata": {
                "availabilityState": metadata.to_mapping(),
            },
        },
        provider_ref=resource.provider_ref,
        last_seen=resource.last_seen,
    )


class _PreviousStateReader:
    def __init__(self, resource: ResourceRecord) -> None:
        self.resource = resource

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str, dict[str, ResourceRecord]]:
        assert resource_ids == (self.resource.resource_id,)
        return "generation-0", {self.resource.resource_id: self.resource}


async def test_enricher_adds_exact_workspace_availability_with_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(
            "/providers/Microsoft.ResourceHealth/availabilityStatuses/current"
        )
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Available",
                    "reasonType": "Unplanned",
                    "reportedTime": OBSERVED.isoformat(),
                }
            },
        )

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    result = enriched.resources[0]
    assert result.props["name"] == "one"
    assert result.props["availabilityState"] == "Available"
    assert result.last_seen == resource.last_seen
    assert enriched.recorded_at == COMPLETED
    metadata = StateFactMetadata.from_mapping(
        result.props["state_fact_metadata"]["availabilityState"]
    )
    assert metadata.source_identity == "azure-resource-health"
    assert metadata.effective_at == OBSERVED
    assert metadata.recorded_at == COMPLETED
    assert metadata.completeness == 1.0
    assert enriched.source_states[0].status is InventoryProjectionSourceStatus.AVAILABLE
    assert enriched.source_states[0].coverage == {"observed": 1, "targets": 1}


async def test_enricher_does_not_copy_workspace_health_to_application_insights() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Application Insights MUST NOT query direct Resource Health")

    resource = _resource("application-insights")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].status is InventoryProjectionSourceStatus.AVAILABLE
    assert enriched.source_states[0].coverage == {"targets": 0}


async def test_enricher_preserves_partial_failure_without_inventing_state() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"code": "UnsupportedResourceType"}})

    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    assert enriched.resources[0].props["availabilityState"] == "Available"
    assert (
        enriched.resources[0].props["state_fact_metadata"] == previous.props["state_fact_metadata"]
    )
    assert enriched.source_states[0].status is InventoryProjectionSourceStatus.UNAVAILABLE
    assert enriched.source_states[0].reason == "resource_health_partial"
    assert enriched.source_states[0].coverage == {"not_modeled": 1, "targets": 1}
    assert enriched.state_base_generation == "generation-0"
    assert enriched.state_base_generation_checked is True


async def test_enricher_rejects_out_of_order_health_and_retains_newer_fact() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Degraded",
                    "reportedTime": (OBSERVED - timedelta(minutes=1)).isoformat(),
                }
            },
        )

    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    assert enriched.resources[0].props["availabilityState"] == "Available"
    assert enriched.source_states[0].reason == "resource_health_partial"
    assert enriched.source_states[0].coverage == {"out_of_order": 1, "targets": 1}


async def test_enricher_retains_prior_fact_on_equal_time_conflict() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Degraded",
                    "reportedTime": OBSERVED.isoformat(),
                }
            },
        )

    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    assert enriched.resources[0].props["availabilityState"] == "Available"
    assert enriched.source_states[0].coverage == {
        "conflicting_same_time": 1,
        "targets": 1,
    }
