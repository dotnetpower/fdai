from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
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
from fdai_service_contracts.recorded_resource_state import (
    AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE,
)

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
OBSERVED = datetime(2026, 9, 6, 1, 0, tzinfo=UTC)
COMPLETED = datetime(2026, 9, 6, 1, 1, tzinfo=UTC)
RESOURCE_HEALTH_PROVIDER_TYPES = {
    "alert-rule": "Microsoft.Insights/scheduledQueryRules",
    "api-gateway": "Microsoft.ApiManagement/service",
    "app-service-plan": "Microsoft.Web/serverFarms",
    "cache": "Microsoft.Cache/redis",
    "compute.function": "Microsoft.Web/sites",
    "compute.vm": "Microsoft.Compute/virtualMachines",
    "compute.vm-scale-set": "Microsoft.Compute/virtualMachineScaleSets",
    "compute.web-app": "Microsoft.Web/sites",
    "event-hub": "Microsoft.EventHub/namespaces",
    "kubernetes-cluster": "Microsoft.ContainerService/managedClusters",
    "llm-endpoint": "Microsoft.CognitiveServices/accounts",
    "log-workspace": "Microsoft.OperationalInsights/workspaces",
    "metrics-workspace": "Microsoft.Monitor/accounts",
    "mysql-server": "Microsoft.DBforMySQL/flexibleServers",
    "network.application-gateway": "Microsoft.Network/applicationGateways",
    "network.dns-resolver": "Microsoft.Network/dnsResolvers",
    "network.dns-resolver-inbound-endpoint": "Microsoft.Network/dnsResolvers/inboundEndpoints",
    "network.dns-zone": "Microsoft.Network/dnsZones",
    "network.firewall": "Microsoft.Network/azureFirewalls",
    "network.load-balancer": "Microsoft.Network/loadBalancers",
    "network.nat-gateway": "Microsoft.Network/natGateways",
    "network.virtual-network-gateway": "Microsoft.Network/virtualNetworkGateways",
    "nosql-database": "Microsoft.DocumentDB/databaseAccounts",
    "object-storage": "Microsoft.Storage/storageAccounts",
    "postgresql-server": "Microsoft.DBforPostgreSQL/flexibleServers",
    "redis-enterprise": "Microsoft.Cache/redisEnterprise",
    "secret-store": "Microsoft.KeyVault/vaults",
    "service-bus-namespace": "Microsoft.ServiceBus/namespaces",
    "sql-database": "Microsoft.Sql/servers/databases",
}


def _resource(resource_type: str = "log-workspace") -> ResourceRecord:
    provider_type = RESOURCE_HEALTH_PROVIDER_TYPES.get(
        resource_type,
        "Microsoft.Insights/components",
    )
    provider_parts = provider_type.split("/")
    provider_path = (
        f"{provider_parts[0]}/{provider_parts[1]}/one"
        if len(provider_parts) == 2
        else f"{provider_parts[0]}/{provider_parts[1]}/parent/{provider_parts[2]}/one"
    )
    return ResourceRecord(
        resource_id=f"scope-example/resource-group/example/providers/{resource_type}/one",
        type=resource_type,
        props={"name": "one", "properties": {"provisioningState": "Succeeded"}},
        provider_ref=(
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/{provider_path}"
        ),
        last_seen=OBSERVED.isoformat(),
    )


def _resource_with_health(
    state: str,
    *,
    observed_at: datetime,
    resource_type: str = "log-workspace",
) -> ResourceRecord:
    resource = _resource(resource_type)
    material = f"{resource.resource_id}|{state}|status_only|{observed_at.isoformat()}"
    evidence_ref = f"azure-resource-health:sha256:{hashlib.sha256(material.encode()).hexdigest()}"
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
        assert self.resource.resource_id in resource_ids
        return "generation-0", {self.resource.resource_id: self.resource}


class _UnavailableIdentity:
    async def get_token(self, _audience: str):
        raise RuntimeError("identity unavailable")


def test_default_bounds_cover_the_reviewed_resource_health_slice() -> None:
    config = AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,))

    assert config.max_targets == 200
    assert config.max_concurrency == 8


async def test_enricher_adds_exact_workspace_availability_with_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "management.usgovcloudapi.net"
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
                audience="https://management.usgovcloudapi.net/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(
                subscription_ids=(SUBSCRIPTION,),
                endpoint="https://management.usgovcloudapi.net",
                audience="https://management.usgovcloudapi.net/.default",
            ),
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
    assert result.props["availabilityReasonKind"] == "unplanned"
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


async def test_enricher_covers_every_reviewed_resource_health_type() -> None:
    requested_resources: set[str] = set()

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_resources.add(
            request.url.path.split(
                "/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
                1,
            )[0].casefold()
        )
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Available",
                    "reportedTime": OBSERVED.isoformat(),
                }
            },
        )

    resource_types = tuple(sorted(AVAILABILITY_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE))
    resources = tuple(_resource(resource_type) for resource_type in resource_types)
    assert set(resource_types) == set(RESOURCE_HEALTH_PROVIDER_TYPES)
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
                resources=resources,
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    assert {resource.type for resource in enriched.resources} == set(resource_types)
    assert requested_resources == {
        resource.provider_ref.casefold()
        for resource in resources
        if resource.provider_ref is not None
    }
    assert all(
        resource.props["availabilityState"] == "Available" for resource in enriched.resources
    )
    assert enriched.source_states[0].coverage == {
        "observed": len(resource_types),
        "targets": len(resource_types),
    }


async def test_enricher_rejects_target_slice_above_the_configured_bound() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("an over-limit Resource Health slice MUST NOT call the provider")

    resource = _resource("object-storage")
    resources = (
        resource,
        replace(
            resource,
            resource_id="scope-example/resource-group/example/providers/object-storage/two",
        ),
        replace(
            resource,
            resource_id="scope-example/resource-group/example/providers/object-storage/three",
        ),
    )
    previous = _resource_with_health(
        "Available",
        observed_at=OBSERVED,
        resource_type="object-storage",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(
                subscription_ids=(SUBSCRIPTION,),
                max_targets=2,
            ),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=resources,
                links=(),
                complete=True,
                recorded_at=OBSERVED,
            )
        )

    assert enriched.resources[0].props["availabilityState"] == "Available"
    assert enriched.resources[1:] == resources[1:]
    assert enriched.source_states[0].status is InventoryProjectionSourceStatus.UNAVAILABLE
    assert enriched.source_states[0].reason == "resource_health_target_limit"
    assert enriched.source_states[0].coverage == {"targets": 3}


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


async def test_enricher_pins_base_generation_when_there_are_no_health_targets() -> None:
    class EmptyPreviousStateReader:
        async def read_active_resources(
            self,
            *,
            resource_ids: tuple[str, ...],
        ) -> tuple[str, dict[str, ResourceRecord]]:
            assert resource_ids == ()
            return "generation-0", {}

    resource = _resource("application-insights")
    async with httpx.AsyncClient() as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=EmptyPreviousStateReader(),
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

    assert enriched.state_base_generation == "generation-0"
    assert enriched.state_base_generation_checked is True


@pytest.mark.parametrize(
    "resource_name",
    ["one\nX", "one%0AX", "one%00X", "one%09X", "one%7FX"],
)
async def test_enricher_rejects_control_characters_in_provider_ref(
    resource_name: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("an invalid ARM id MUST NOT call Resource Health")

    resource = replace(
        _resource("object-storage"),
        provider_ref=(
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            f"providers/Microsoft.Storage/storageAccounts/{resource_name}"
        ),
    )
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
    assert enriched.source_states[0].coverage == {"target_unresolved": 1, "targets": 1}


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


async def test_enricher_retains_prior_health_during_identity_outage() -> None:
    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    async with httpx.AsyncClient() as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
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
    assert enriched.source_states[0].reason == "resource_health_identity_unavailable"


async def test_enricher_ignores_overflowing_prior_health_metadata() -> None:
    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    previous_metadata = dict(previous.props["state_fact_metadata"])
    availability_metadata = dict(previous_metadata["availabilityState"])
    availability_metadata["completeness"] = 10**10_000
    previous_metadata["availabilityState"] = availability_metadata
    malformed_previous = replace(
        previous,
        props={
            **previous.props,
            "state_fact_metadata": previous_metadata,
        },
    )
    async with httpx.AsyncClient() as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(malformed_previous),
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
    assert enriched.source_states[0].reason == "resource_health_identity_unavailable"


async def test_enricher_ignores_noncanonical_prior_health_value() -> None:
    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    malformed_previous = replace(
        previous,
        props={
            **previous.props,
            "availabilityState": "Healthy",
        },
    )
    async with httpx.AsyncClient() as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(malformed_previous),
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
    assert enriched.source_states[0].reason == "resource_health_identity_unavailable"


async def test_enricher_normalizes_reason_kind_and_rejects_malformed_prior_reason() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Available",
                    "reasonType": "User Initiated / Planned",
                    "reportedTime": OBSERVED.isoformat(),
                }
            },
        )

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        observed = await AzureResourceHealthInventoryEnricher(
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

    assert observed.resources[0].props["availabilityReasonKind"] == "user_initiated_planned"
    malformed_previous = replace(
        observed.resources[0],
        props={
            **observed.resources[0].props,
            "availabilityReasonKind": "not/canonical",
        },
    )
    async with httpx.AsyncClient() as client:
        retained = await AzureResourceHealthInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(malformed_previous),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-2",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=COMPLETED,
            )
        )

    assert retained.resources == (resource,)


@pytest.mark.parametrize(
    "evidence_ref",
    [
        "unbound-revision",
        "azure-resource-health:sha256:" + "f" * 64,
    ],
)
async def test_enricher_rejects_unbound_prior_health_evidence_ref(evidence_ref: str) -> None:
    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    previous_metadata = dict(previous.props["state_fact_metadata"])
    availability_metadata = dict(previous_metadata["availabilityState"])
    availability_metadata["source_revision"] = evidence_ref
    availability_metadata["evidence_refs"] = [evidence_ref]
    previous_metadata["availabilityState"] = availability_metadata
    malformed_previous = replace(
        previous,
        props={
            **previous.props,
            "state_fact_metadata": previous_metadata,
        },
    )
    async with httpx.AsyncClient() as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(malformed_previous),
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


async def test_enricher_rejects_prior_health_without_a_reason_kind() -> None:
    resource = _resource()
    previous = _resource_with_health("Available", observed_at=OBSERVED)
    malformed_previous = replace(
        previous,
        props={
            key: value for key, value in previous.props.items() if key != "availabilityReasonKind"
        },
    )
    async with httpx.AsyncClient() as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(malformed_previous),
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
    conflicted = StateFactMetadata.from_mapping(
        enriched.resources[0].props["state_fact_metadata"]["availabilityState"]
    )
    assert conflicted.completeness == 0.0
    assert conflicted.conflicts == ("equal_time_conflict",)
    assert enriched.source_states[0].coverage == {
        "conflicting_same_time": 1,
        "targets": 1,
    }


async def test_enricher_retains_prior_fact_on_equal_time_reason_conflict() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Available",
                    "reasonType": "Planned",
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

    assert enriched.resources[0].props["availabilityReasonKind"] == "status_only"
    conflicted = StateFactMetadata.from_mapping(
        enriched.resources[0].props["state_fact_metadata"]["availabilityState"]
    )
    assert conflicted.completeness == 0.0
    assert conflicted.conflicts == ("equal_time_conflict",)
    assert enriched.source_states[0].coverage == {
        "conflicting_same_time": 1,
        "targets": 1,
    }

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repeated = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(enriched.resources[0]),
            clock=lambda: COMPLETED,
        ).enrich(
            PromotedInventoryObservation(
                generation="generation-2",
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=COMPLETED,
            )
        )

    repeated_fact = StateFactMetadata.from_mapping(
        repeated.resources[0].props["state_fact_metadata"]["availabilityState"]
    )
    assert repeated_fact.completeness == 0.0
    assert repeated_fact.conflicts == ("equal_time_conflict",)


@pytest.mark.parametrize(
    "provider_ref",
    [
        (
            f"subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.OperationalInsights/workspaces/one"
        ),
        (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.OperationalInsights/workspaces/../../../../"
            "subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/other/"
            "providers/Microsoft.OperationalInsights/workspaces/other"
        ),
        (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.OperationalInsights/workspaces/%2e%2e/other"
        ),
    ],
)
async def test_enricher_rejects_unsafe_arm_id_without_sending_token(
    provider_ref: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("relative ARM id MUST NOT issue a request")

    resource = _resource()
    resource = replace(resource, provider_ref=provider_ref)
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

    assert enriched.source_states[0].coverage == {"target_unresolved": 1, "targets": 1}


async def test_enricher_bounds_response_before_json_decode() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1025)

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureResourceHealthInventoryEnricher(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic test value
            ),
            http_client=client,
            config=AzureResourceHealthInventoryConfig(
                subscription_ids=(SUBSCRIPTION,),
                max_response_bytes=1024,
            ),
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

    assert enriched.source_states[0].coverage == {"response_too_large": 1, "targets": 1}


async def test_enricher_classifies_timestamp_conversion_overflow() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "availabilityState": "Available",
                    "reportedTime": "0001-01-01T00:00:00+14:00",
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

    assert enriched.source_states[0].coverage == {"response_invalid": 1, "targets": 1}
