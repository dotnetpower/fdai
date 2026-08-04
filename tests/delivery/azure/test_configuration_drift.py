from __future__ import annotations

import json

import httpx
import pytest

from fdai.delivery.azure import configuration_drift
from fdai.delivery.azure.arg_query import ArgQueryError
from fdai.delivery.azure.arg_transport import ArgThrottleGate
from fdai.delivery.azure.configuration_drift import (
    AzureArgConfigurationObservationSource,
    AzureConfigurationObservationConfig,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


def _config() -> AzureConfigurationObservationConfig:
    return AzureConfigurationObservationConfig(
        scope_ref="configured-drift-scope",
        subscription_scope=_SUBSCRIPTION,
        resource_group="rg-example",
        page_size=100,
        max_pages=2,
        timeout_seconds=5.0,
    )


async def test_arg_observation_is_filtered_at_query_and_redacts_arm_ids() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.update(body)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": (
                            f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/"
                            "providers/Microsoft.ContainerService/managedClusters/aks-example"
                        ),
                        "type": "Microsoft.ContainerService/managedClusters",
                        "name": "aks-example",
                        "location": "Korea Central",
                        "kind": "Base",
                        "sku": {"name": "Base", "tier": "Free"},
                        "properties": {
                            "provisioningState": "Succeeded",
                            "powerState": "Stopped",
                            "publicNetworkAccess": "Disabled",
                            "kubernetesVersion": "1.34",
                        },
                        "resourceGroup": "rg-example",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106
            ),
            http_client=client,
            config=_config(),
        )
        observation = await source.observe(scope="configured-drift-scope")

    assert captured["subscriptions"] == [_SUBSCRIPTION]
    assert "where resourceGroup =~ 'rg-example'" in str(captured["query"])
    assert observation.completeness.value == "complete"
    assert len(observation.resources) == 1
    resource = observation.resources[0]
    assert resource.local_name == "aks-example"
    assert resource.resource_type == "microsoft.containerservice/managedclusters"
    assert resource.attributes == {
        "kind": "Base",
        "kubernetes_version": "1.34",
        "power_state": "Stopped",
        "provisioning_state": "Succeeded",
        "public_network_access": "Disabled",
        "sku_name": "Base",
        "sku_tier": "Free",
    }
    assert len(observation.links) == 1
    assert observation.links[0].to_dict() == {
        "source": "resource-group:rg-example",
        "relation": "contains",
        "target": "microsoft.containerservice/managedclusters:aks-example",
    }
    assert _SUBSCRIPTION not in json.dumps(resource.to_dict())
    assert _SUBSCRIPTION not in json.dumps(observation.links[0].to_dict())
    assert "/subscriptions/" not in json.dumps(resource.to_dict())


async def test_scope_mismatch_is_rejected_before_arg_call() -> None:
    called = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106
            ),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(PermissionError, match="outside"):
            await source.observe(scope="another-scope")

    assert not called


async def test_repeated_observations_share_one_arg_throttle_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gates: list[ArgThrottleGate] = []

    async def _capture_gate(**kwargs):  # type: ignore[no-untyped-def]
        gates.append(kwargs["throttle_gate"])
        return (), ()

    monkeypatch.setattr(configuration_drift, "fetch_arg_pages", _capture_gate)

    async with httpx.AsyncClient() as client:
        source = AzureArgConfigurationObservationSource(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106
            ),
            http_client=client,
            config=_config(),
        )
        await source.observe(scope="configured-drift-scope")
        await source.observe(scope="configured-drift-scope")

    assert len(gates) == 2
    assert gates[0] is gates[1]


async def test_arg_pagination_cap_fails_without_partial_observation() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": [], "$skipToken": "more"})

    config = AzureConfigurationObservationConfig(
        scope_ref="configured-drift-scope",
        subscription_scope=_SUBSCRIPTION,
        resource_group="rg-example",
        page_size=100,
        max_pages=1,
        timeout_seconds=5.0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureArgConfigurationObservationSource(
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",  # noqa: S106
            ),
            http_client=client,
            config=config,
        )
        with pytest.raises(ArgQueryError, match="pagination cap"):
            await source.observe(scope="configured-drift-scope")

    assert calls == 1


def test_resource_group_filter_rejects_kusto_injection() -> None:
    with pytest.raises(ValueError, match="resource_group"):
        AzureConfigurationObservationConfig(
            scope_ref="configured-drift-scope",
            subscription_scope=_SUBSCRIPTION,
            resource_group="rg-example' | take 1",
        )
