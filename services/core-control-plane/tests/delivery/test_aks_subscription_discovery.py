from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import yaml
from fdai.delivery.aks_subscription_discovery import (
    AksSubscriptionDiscoveryConfig,
    AksSubscriptionDiscoveryError,
    AzureAksSubscriptionBindingDiscovery,
)
from fdai.shared.providers.workload_identity import IdentityToken

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_CLUSTER_ONE = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/providers/"
    "Microsoft.ContainerService/managedClusters/aks-one"
)
_CLUSTER_TWO = _CLUSTER_ONE.replace("aks-one", "aks-two")
_CA = "-----BEGIN CERTIFICATE-----\nZXhhbXBsZQ==\n-----END CERTIFICATE-----\n"


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="short-lived-token",
            audience=audience,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


def _cluster(cluster_ref: str) -> dict[str, Any]:
    return {
        "id": cluster_ref,
        "properties": {
            "aadProfile": {"enableAzureRBAC": True, "managed": True},
            "enableRBAC": True,
            "provisioningState": "Succeeded",
        },
    }


def _credential(cluster_ref: str, *, static_token: bool = False) -> dict[str, Any]:
    name = cluster_ref.rsplit("/", maxsplit=1)[-1]
    user: dict[str, Any] = {
        "exec": {
            "apiVersion": "client.authentication.k8s.io/v1beta1",
            "args": ["get-token", "--server-id", "aks-audience"],
            "command": "kubelogin",
            "interactiveMode": "Never",
        }
    }
    if static_token:
        user["token"] = "must-not-be-retained"
    kubeconfig = {
        "apiVersion": "v1",
        "clusters": [
            {
                "name": name,
                "cluster": {
                    "certificate-authority-data": base64.b64encode(_CA.encode()).decode(),
                    "server": f"https://{name}.example",
                },
            }
        ],
        "contexts": [{"name": name, "context": {"cluster": name, "user": name}}],
        "current-context": name,
        "kind": "Config",
        "users": [{"name": name, "user": user}],
    }
    encoded = base64.b64encode(yaml.safe_dump(kubeconfig).encode()).decode()
    return {"kubeconfigs": [{"name": "clusterUser", "value": encoded}]}


def _discovery(handler: Any, **config_overrides: Any) -> AzureAksSubscriptionBindingDiscovery:
    return AzureAksSubscriptionBindingDiscovery(
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AksSubscriptionDiscoveryConfig(
            management_endpoint="https://management.azure.com",
            management_audience="https://management.azure.com/.default",
            **config_overrides,
        ),
    )


@pytest.mark.asyncio
async def test_discovery_includes_a_new_cluster_without_configuration_change() -> None:
    listed = [_CLUSTER_ONE]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": [_cluster(item) for item in listed]})
        cluster_ref = _CLUSTER_TWO if "aks-two" in request.url.path else _CLUSTER_ONE
        return httpx.Response(200, json=_credential(cluster_ref))

    discovery = _discovery(handler)
    first = await discovery.discover(_SUBSCRIPTION)
    listed.append(_CLUSTER_TWO)
    second = await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert [item.cluster_ref for item in first.bindings] == [_CLUSTER_ONE]
    assert [item.cluster_ref for item in second.bindings] == [_CLUSTER_ONE, _CLUSTER_TWO]
    assert all(item.auth_mode == "workload-identity" for item in second.bindings)
    assert all(item.audience == "aks-audience" for item in second.bindings)
    assert second.unavailable_scopes == ()


@pytest.mark.asyncio
async def test_discovery_rejects_embedded_credentials_per_cluster() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": [_cluster(_CLUSTER_ONE)]})
        return httpx.Response(200, json=_credential(_CLUSTER_ONE, static_token=True))

    discovery = _discovery(handler)
    result = await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert result.bindings == ()
    assert len(result.unavailable_scopes) == 1
    assert result.unavailable_scopes[0].reason == "kubernetes_discovered_binding_unavailable"


@pytest.mark.asyncio
async def test_discovery_rejects_incomplete_pagination() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [_cluster(_CLUSTER_ONE)],
                "nextLink": "https://management.azure.com/next",
            },
        )

    discovery = _discovery(handler, max_pages=1)
    with pytest.raises(AksSubscriptionDiscoveryError, match="pagination cap"):
        await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()
