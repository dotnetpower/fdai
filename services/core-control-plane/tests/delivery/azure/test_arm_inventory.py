"""Direct ARM inventory fallback tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fdai.delivery.azure.arm_inventory import (
    ArmInventoryError,
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _vocabulary():
    path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )


async def test_arm_fallback_pages_and_emits_contains_link() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": (
                                "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                                "Microsoft.Compute/virtualMachines/vm-1"
                            ),
                            "name": "vm-1",
                            "location": "example-region",
                        }
                    ],
                    "nextLink": "https://management.azure.com/next?page=2",
                },
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_query_fn()
        resources, links = await query("compute.vm")

    assert calls == 2
    assert resources[0].resource_id.endswith("providers/microsoft.compute/virtualmachines/vm-1")
    assert links[0].from_id.endswith("/resource-group/rg-1")
    assert links[0].to_id == resources[0].resource_id
    assert resources[0].props["parent_id"] == links[0].from_id


async def test_arm_fallback_lists_private_dns_zone_group_children() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/resources"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": (
                                "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                                "Microsoft.Network/privateEndpoints/pe-1"
                            ),
                            "name": "pe-1",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": (
                            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                            "Microsoft.Network/privateEndpoints/pe-1/"
                            "privateDnsZoneGroups/default"
                        ),
                        "name": "default",
                        "properties": {
                            "privateDnsZoneConfigs": [
                                {
                                    "properties": {
                                        "privateDnsZoneId": (
                                            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                                            "Microsoft.Network/privateDnsZones/privatelink.example"
                                        )
                                    }
                                }
                            ]
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_query_fn()
        resources, links = await query("network.private-dns-zone-group")

    assert requested_paths == [
        "/subscriptions/sub-1/resources",
        (
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Network/"
            "privateEndpoints/pe-1/privateDnsZoneGroups"
        ),
    ]
    assert resources[0].type == "network.private-dns-zone-group"
    by_mapping = {
        link.mapping_evidence.mapping_id: link
        for link in links
        if link.mapping_evidence is not None
    }
    contains = by_mapping["azure.private-endpoint-contains-dns-zone-group"]
    attached = by_mapping["azure.private-dns-zone-group-attached-to-zone"]
    assert resources[0].props["parent_id"] == contains.from_id
    assert contains.to_id == resources[0].resource_id
    assert attached.from_id == resources[0].resource_id
    assert len(links) == 2


async def test_arm_fallback_lists_aks_agent_pool_children() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/resources"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": (
                                "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                                "Microsoft.ContainerService/managedClusters/aks-1"
                            ),
                            "name": "aks-1",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": (
                            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                            "Microsoft.ContainerService/managedClusters/aks-1/"
                            "agentPools/system"
                        ),
                        "name": "system",
                        "properties": {"count": 3},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_query_fn()
        resources, links = await query("kubernetes-node-pool")

    assert requested_paths == [
        "/subscriptions/sub-1/resources",
        (
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
            "Microsoft.ContainerService/managedClusters/aks-1/agentPools"
        ),
    ]
    assert resources[0].type == "kubernetes-node-pool"
    assert (
        resources[0]
        .props["parent_id"]
        .endswith("/providers/microsoft.containerservice/managedclusters/aks-1")
    )
    contains = next(
        link
        for link in links
        if link.mapping_evidence is not None
        and link.mapping_evidence.mapping_id == "azure.aks-contains-agent-pool"
    )
    assert contains.from_id == resources[0].props["parent_id"]
    assert contains.to_id == resources[0].resource_id
    assert contains.mapping_evidence is not None
    assert contains.mapping_evidence.source_identity == "azure-resource-manager-containerservice"


async def test_arm_fallback_rejects_cross_host_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"value": [], "nextLink": "https://untrusted.example/next"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_query_fn()
        with pytest.raises(ArmInventoryError, match="scheme or host"):
            await query("compute.vm")


@pytest.mark.parametrize(
    "payload",
    [
        {"value": ["not-an-object"]},
        {"value": [{"name": "missing-id"}]},
        {"value": [], "nextLink": 42},
        {"value": [], "nextLink": ""},
    ],
)
async def test_arm_fallback_rejects_malformed_pages(payload: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_query_fn()
        with pytest.raises(ArmInventoryError):
            await query("compute.vm")


def test_arm_config_rejects_insecure_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        AzureArmInventoryFactoryConfig(
            subscription_scopes=("sub-1",),
            arm_endpoint="http://management.example",
        )
