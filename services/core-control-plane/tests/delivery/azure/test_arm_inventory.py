"""Direct ARM inventory fallback tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fdai.delivery.azure import arm_inventory
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.azure.arm_inventory import (
    ArmInventoryError,
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
    _project_vmss_instance_state,
)
from fdai.delivery.azure.inventory import ResourceQueryResult
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.providers.inventory import ResourceRecord
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
    assert resources[0].props["subscriptionId"] == "sub-1"
    assert resources[0].props["resourceGroup"] == "rg-1"
    assert resources[0].props["providerType"] == "Microsoft.Compute/virtualMachines"


async def test_arm_fallback_preserves_readable_model_deployment_facts() -> None:
    account_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
        "Microsoft.CognitiveServices/accounts/ai-example"
    )
    deployment_id = f"{account_id}/deployments/gpt-example"
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/resources"):
            return httpx.Response(
                200,
                json={"value": [{"id": account_id, "name": "ai-example"}]},
            )
        assert request.url.params["api-version"] == "2024-10-01"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": deployment_id,
                        "name": "gpt-example",
                        "sku": {"name": "GlobalStandard", "capacity": 50},
                        "properties": {
                            "provisioningState": "Succeeded",
                            "currentCapacity": 40,
                            "rateLimits": [{"key": "token", "count": 50_000, "renewalPeriod": 60}],
                            "model": {
                                "format": "OpenAI",
                                "name": "gpt-5.4",
                                "version": "2026-09-01",
                            },
                        },
                    }
                ]
            },
        )

    async def primary_query(_resource_type: str) -> ResourceQueryResult:
        raise AssertionError("model deployments MUST use the ARM child collection")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_child_overlay_query_fn(primary_query)
        resources, links = await query("llm-model-deployment")

    assert requested_paths == [
        "/subscriptions/sub-1/resources",
        (
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
            "Microsoft.CognitiveServices/accounts/ai-example/deployments"
        ),
    ]
    deployment = resources[0]
    assert deployment.resource_id == to_neutral_id(deployment_id)
    assert deployment.props["model_name"] == "gpt-5.4"
    assert deployment.props["model_version"] == "2026-09-01"
    assert deployment.props["provisioning_state"] == "Succeeded"
    assert deployment.props["sku_name"] == "GlobalStandard"
    assert deployment.props["capacity_units"] == 50
    assert deployment.props["current_capacity_units"] == 40
    assert deployment.props["capacity_transitioning"] is True
    assert deployment.props["capacity_tpm"] == 50_000
    assert deployment.props["capacity_tpm_source"] == "properties.rateLimits"
    assert deployment.props["subscriptionId"] == "sub-1"
    assert deployment.props["resourceGroup"] == "rg-1"
    assert deployment.props["providerType"] == "Microsoft.CognitiveServices/accounts/deployments"
    assert deployment.props["parent_id"].endswith("microsoft.cognitiveservices/accounts/ai-example")
    contains = next(link for link in links if link.link_type == "contains")
    assert contains.from_id == to_neutral_id(account_id)
    assert contains.to_id == deployment.resource_id
    assert contains.mapping_evidence is not None
    assert contains.mapping_evidence.source_identity == "azure-resource-manager-cognitiveservices"


async def test_arm_fallback_bounds_model_deployment_parent_collections() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/resources")
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": (
                            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                            "Microsoft.CognitiveServices/accounts/ai-one"
                        )
                    },
                    {
                        "id": (
                            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                            "Microsoft.CognitiveServices/accounts/ai-two"
                        )
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(
                subscription_scopes=("sub-1",),
                max_child_collections=1,
            ),
        ).build_query_fn()
        with pytest.raises(ArmInventoryError, match="Cognitive Services child collection cap"):
            await query("llm-model-deployment")


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
    assert resources[0].props["subscriptionId"] == "sub-1"
    assert resources[0].props["resourceGroup"] == "rg-1"
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
    assert resources[0].props["subscriptionId"] == "sub-1"
    assert resources[0].props["resourceGroup"] == "rg-1"
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
    assert [link for link in links if link.link_type == "contains"] == [contains]


async def test_arm_overlay_lists_vm_scale_set_vm_and_nic_children() -> None:
    requested_paths: list[str] = []
    scale_set_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
        "Microsoft.Compute/virtualMachineScaleSets/vmss-1"
    )
    virtual_machine_id = f"{scale_set_id}/virtualMachines/0"
    network_interface_id = f"{virtual_machine_id}/networkInterfaces/nic-0"

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/resources"):
            return httpx.Response(200, json={"value": [{"id": scale_set_id, "name": "vmss-1"}]})
        if request.url.path.endswith("/virtualMachines"):
            assert request.url.params["$expand"] == "instanceView"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": virtual_machine_id,
                            "name": "0",
                            "properties": {
                                "instanceView": {
                                    "statuses": [
                                        {
                                            "code": "PowerState/running",
                                            "message": "provider detail must not persist",
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": network_interface_id,
                        "name": "nic-0",
                        "properties": {
                            "ipConfigurations": [
                                {
                                    "properties": {
                                        "subnet": {
                                            "id": (
                                                "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                                                "Microsoft.Network/virtualNetworks/vnet-1/subnets/subnet-1"
                                            )
                                        }
                                    }
                                }
                            ]
                        },
                    }
                ]
            },
        )

    async def primary_query(_resource_type: str) -> ResourceQueryResult:
        return ResourceQueryResult(
            resources=(
                ResourceRecord(
                    resource_id=to_neutral_id(scale_set_id),
                    type="compute.vm-scale-set",
                    props={"name": "vmss-1"},
                    provider_ref=scale_set_id,
                ),
            )
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_child_overlay_query_fn(primary_query)
        result = await query("compute.vm-scale-set")

    assert isinstance(result, ResourceQueryResult)
    assert requested_paths == [
        "/subscriptions/sub-1/resources",
        (
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/"
            "virtualMachineScaleSets/vmss-1/virtualMachines"
        ),
        (
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/"
            "virtualMachineScaleSets/vmss-1/virtualMachines/0/networkInterfaces"
        ),
    ]
    assert [resource.type for resource in result.resources] == [
        "compute.vm-scale-set",
        "compute.vm",
        "network.interface",
    ]
    for resource in result.resources:
        if resource.type == "compute.vm-scale-set":
            continue
        assert resource.props["subscriptionId"] == "sub-1"
        assert resource.props["resourceGroup"] == "rg-1"
    virtual_machine = next(
        resource for resource in result.resources if resource.type == "compute.vm"
    )
    assert virtual_machine.props["properties"]["instanceView"] == {
        "powerState": {"code": "PowerState/running"}
    }
    assert "provider detail must not persist" not in repr(virtual_machine.props)
    by_mapping = {
        link.mapping_evidence.mapping_id: link
        for link in result.links
        if link.mapping_evidence is not None
    }
    contains = by_mapping["azure.vm-scale-set-contains-vm"]
    attached = by_mapping["azure.vm-scale-set-nic-attached-to-vm"]
    subnet = by_mapping["azure.vm-scale-set-nic-attached-to-subnet"]
    assert contains.from_id == to_neutral_id(scale_set_id)
    assert contains.to_id == to_neutral_id(virtual_machine_id)
    assert attached.from_id == to_neutral_id(network_interface_id)
    assert attached.to_id == contains.to_id
    assert subnet.from_id == attached.from_id
    assert result.relationship_drops == ()
    assert all(link.mapping_evidence is not None for link in result.links)


async def test_arm_overlay_hydrates_only_vm_run_command_execution_state() -> None:
    command_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/"
        "virtualMachines/vm-1/runCommands/example-command"
    )
    requested: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        return httpx.Response(
            200,
            json={
                "id": command_id,
                "type": "Microsoft.Compute/virtualMachines/runCommands",
                "properties": {
                    "instanceView": {
                        "executionState": "Succeeded",
                        "output": "sensitive output",
                        "error": "sensitive error",
                    }
                },
            },
        )

    async def primary_query(_resource_type: str) -> ResourceQueryResult:
        return ResourceQueryResult(
            resources=(
                ResourceRecord(
                    resource_id=to_neutral_id(command_id),
                    type="compute.vm-run-command",
                    props={
                        "name": "example-command",
                        "properties": {"provisioningState": "Succeeded"},
                    },
                    provider_ref=command_id,
                ),
            )
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(subscription_scopes=("sub-1",)),
        ).build_child_overlay_query_fn(primary_query)
        result = await query("compute.vm-run-command")

    assert isinstance(result, ResourceQueryResult)
    assert len(requested) == 1
    assert requested[0].params["$expand"] == "instanceView"
    assert result.resources[0].props["properties"] == {
        "provisioningState": "Succeeded",
        "instanceView": {"executionState": "Succeeded"},
    }
    assert "sensitive output" not in repr(result.resources[0].props)
    assert "sensitive error" not in repr(result.resources[0].props)
    assert result.resources[0].last_seen is None


@pytest.mark.parametrize(
    "instance_view",
    [
        {"message": "sensitive status"},
        {"statuses": None, "message": "sensitive status"},
        {"statuses": {"code": "PowerState/running"}, "message": "sensitive status"},
    ],
)
def test_vmss_instance_view_is_scrubbed_when_statuses_are_missing_or_malformed(
    instance_view: object,
) -> None:
    projected = _project_vmss_instance_state(
        {
            "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
            "Microsoft.Compute/virtualMachineScaleSets/vmss-1/virtualMachines/0",
            "properties": {"instanceView": instance_view},
        }
    )

    assert projected["properties"]["instanceView"] == {}
    assert "sensitive status" not in repr(projected)


def test_vm_run_command_scrubs_prior_instance_view_when_execution_state_is_missing() -> None:
    resource = ResourceRecord(
        resource_id="run-command-1",
        type="compute.vm-run-command",
        props={
            "properties": {
                "provisioningState": "Succeeded",
                "instanceView": {
                    "output": "sensitive output",
                    "error": "sensitive error",
                },
            }
        },
        provider_ref=(
            "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/"
            "virtualMachines/vm-1/runCommands/example-command"
        ),
    )
    sanitized = arm_inventory._with_vm_run_command_state(
        resource,
        {
            "id": resource.provider_ref,
            "properties": {"instanceView": {"output": "new output"}},
        },
    )

    assert sanitized.props["properties"] == {
        "provisioningState": "Succeeded",
        "instanceView": {},
    }
    assert "sensitive" not in repr(sanitized.props)
    assert "new output" not in repr(sanitized.props)


async def test_arm_overlay_bounds_vm_scale_set_child_collections() -> None:
    scale_set_id = (
        "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
        "Microsoft.Compute/virtualMachineScaleSets/vmss-1"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/resources"):
            return httpx.Response(200, json={"value": [{"id": scale_set_id, "name": "vmss-1"}]})
        return httpx.Response(
            200,
            json={
                "value": [
                    {"id": f"{scale_set_id}/virtualMachines/0", "name": "0"},
                ]
            },
        )

    async def primary_query(_resource_type: str) -> ResourceQueryResult:
        return ResourceQueryResult()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        query = AzureArmInventoryFactory(
            identity=_identity(),
            resource_types=_vocabulary(),
            http_client=client,
            config=AzureArmInventoryFactoryConfig(
                subscription_scopes=("sub-1",),
                max_child_collections=1,
            ),
        ).build_child_overlay_query_fn(primary_query)
        with pytest.raises(ArmInventoryError, match="child collection cap"):
            await query("compute.vm-scale-set")


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


async def test_arm_fallback_rejects_provider_type_that_conflicts_with_the_arm_id() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": (
                            "/subscriptions/sub-1/resourceGroups/rg-1/providers/"
                            "Microsoft.Compute/virtualMachines/vm-1"
                        ),
                        "type": "Microsoft.Storage/storageAccounts",
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
        with pytest.raises(ArmInventoryError, match="conflicting provider type"):
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
