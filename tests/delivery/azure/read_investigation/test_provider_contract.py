from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fdai.delivery.azure.read_investigation import (
    AzureCliReadInvestigationAdapter,
    AzureRestReadInvestigationAdapter,
    AzureRow,
)
from fdai.shared.providers.read_investigation import (
    ReadEvidenceEnvelope,
    ReadInvestigationProvider,
    ReadToolLimits,
    ResourceResolutionStatus,
    ResourceSelector,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)
LIMITS = ReadToolLimits(timeout_seconds=10, max_results=8, max_output_bytes=64_000)
RAW_RESOURCE_ID = (
    "/subscriptions/example/resourceGroups/rg-example/"
    "providers/Microsoft.Compute/virtualMachines/vm-01"
)
RAW_CALLER = "caller@example.com"


class _Transport:
    def __init__(self, transport_id: str) -> None:
        self.transport_id = transport_id

    async def resolve_resources(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del selector, limits
        return [
            {
                "id": RAW_RESOURCE_ID,
                "name": "vm-01",
                "type": "compute.vm",
                "resource_group": "rg-example",
            }
        ]

    async def get_resource_state(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return [{"observed_at": NOW.isoformat(), "status": "ok", "state": "stopped"}]

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return [
            {
                "occurred_at": NOW.isoformat(),
                "status": "Succeeded",
                "operation": "Microsoft.Compute/virtualMachines/deallocate/action",
                "caller": RAW_CALLER,
                "caller_kind": "user",
                "correlation": "provider-correlation",
            },
            {"_truncated": True},
        ]

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return [
            {
                "occurred_at": NOW.isoformat(),
                "status": "available",
                "health_kind": "platform_initiated",
            }
        ]

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return [{"occurred_at": NOW.isoformat(), "status": "observed"}]

    async def query_network_security(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return [
            {
                "observed_at": NOW.isoformat(),
                "status": "Allow",
                "rule_name": "allow-https",
                "rule_kind": "custom",
                "direction": "Inbound",
                "protocol": "Tcp",
                "source_prefixes": "Internet",
                "source_ports": "*",
                "destination_prefixes": "*",
                "destination_ports": "443",
                "priority": 200,
                "associations": "subnet:app",
            }
        ]

    async def query_network_peerings(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return [
            {
                "observed_at": NOW.isoformat(),
                "status": "Connected",
                "peering_name": "hub-to-spoke",
                "remote_vnet": "vnet-spoke",
                "sync_level": "FullyInSync",
                "allow_vnet_access": True,
                "allow_forwarded_traffic": True,
                "allow_gateway_transit": True,
                "use_remote_gateways": False,
                "remote_address_prefixes": "10.20.0.0/16",
            }
        ]


async def _normalized(adapter: ReadInvestigationProvider) -> tuple[object, ...]:
    resolution_attempt = await adapter.resolve_resource(
        ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        limits=LIMITS,
    )
    assert resolution_attempt.resolution.status is ResourceResolutionStatus.MATCHED
    resource = resolution_attempt.resolution.resource
    assert resource is not None
    return (
        resource,
        (await adapter.get_resource_state(resource, limits=LIMITS)).evidence,
        (
            await adapter.query_resource_activity(resource, lookback_seconds=3_600, limits=LIMITS)
        ).evidence,
        (
            await adapter.query_resource_health(resource, lookback_seconds=3_600, limits=LIMITS)
        ).evidence,
        (
            await adapter.query_guest_shutdown_events(
                resource, lookback_seconds=3_600, limits=LIMITS
            )
        ).evidence,
        (await adapter.query_network_security(resource, limits=LIMITS)).evidence,
        (await adapter.query_network_peerings(resource, limits=LIMITS)).evidence,
    )


async def test_rest_and_typed_cli_produce_the_same_normalized_envelopes() -> None:
    rest = AzureRestReadInvestigationAdapter(_Transport("rest"), clock=lambda: NOW)
    cli = AzureCliReadInvestigationAdapter(_Transport("cli"), clock=lambda: NOW)
    rest_result = await _normalized(rest)
    cli_result = await _normalized(cli)
    assert rest_result == cli_result
    assert RAW_RESOURCE_ID not in repr(rest_result)
    assert RAW_CALLER not in repr(rest_result)
    network_security = rest_result[-2]
    network_peering = rest_result[-1]
    assert isinstance(network_security, ReadEvidenceEnvelope)
    assert isinstance(network_peering, ReadEvidenceEnvelope)
    assert dict(network_security.records[0].details)["destination_ports"] == "443"
    assert dict(network_peering.records[0].details)["sync_level"] == "FullyInSync"


async def test_ambiguous_resolution_is_bounded_and_does_not_bind_a_resource() -> None:
    class _Ambiguous(_Transport):
        async def resolve_resources(
            self, selector: ResourceSelector, *, limits: ReadToolLimits
        ) -> Sequence[AzureRow]:
            del selector, limits
            return [
                {
                    "id": f"/subscriptions/example/resourceGroups/rg-{index}/providers/type/vm-01",
                    "name": "vm-01",
                    "type": "compute.vm",
                    "resource_group": f"rg-{index}",
                }
                for index in range(20)
            ]

    adapter = AzureRestReadInvestigationAdapter(_Ambiguous("rest"), clock=lambda: NOW)
    attempt = await adapter.resolve_resource(
        ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        limits=LIMITS,
    )
    assert attempt.resolution.status is ResourceResolutionStatus.AMBIGUOUS
    assert len(attempt.resolution.candidates) == 8
    assert attempt.resolution.resource is None
    assert attempt.receipt.truncated is True

    too_small = await adapter.resolve_resource(
        ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        limits=ReadToolLimits(timeout_seconds=10, max_results=1, max_output_bytes=64_000),
    )
    assert too_small.resolution.status is ResourceResolutionStatus.UNAVAILABLE
    assert too_small.resolution.resource is None
