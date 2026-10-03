from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import yaml
from fdai.delivery.aks_subscription_discovery import (
    AksSubscriptionDiscoveryConfig,
    AksSubscriptionDiscoveryError,
    AzureAksSubscriptionBindingDiscovery,
    StateStoreAksSubscriptionBindingCache,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.workload_identity import IdentityToken

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_CLUSTER_ONE = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/providers/"
    "Microsoft.ContainerService/managedClusters/aks-one"
)
_CLUSTER_TWO = _CLUSTER_ONE.replace("aks-one", "aks-two")
_CA = "-----BEGIN CERTIFICATE-----\nZXhhbXBsZQ==\n-----END CERTIFICATE-----\n"


def _cache_key(cluster_ref: str) -> str:
    return "aks-binding-cache:" + hashlib.sha256(cluster_ref.casefold().encode()).hexdigest()


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="short-lived-token",
            audience=audience,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


def _cluster(
    cluster_ref: str,
    *,
    fqdn: str | None = None,
    etag: str | None = None,
) -> dict[str, Any]:
    cluster: dict[str, Any] = {
        "id": cluster_ref,
        "properties": {
            "aadProfile": {"enableAzureRBAC": True, "managed": True},
            "enableRBAC": True,
            "provisioningState": "Succeeded",
        },
    }
    if fqdn is not None:
        cluster["properties"]["fqdn"] = fqdn
    if etag is not None:
        cluster["etag"] = etag
    return cluster


def _credential(
    cluster_ref: str,
    *,
    static_token: bool = False,
    ca_pem: str = _CA,
) -> dict[str, Any]:
    name = cluster_ref.rsplit("/", maxsplit=1)[-1]
    user: dict[str, Any] = {
        "exec": {
            "apiVersion": "client.authentication.k8s.io/v1beta1",
            "args": ["get-token", "--server-id", "aks-audience"],
            "command": "kubelogin",
            "env": [],
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
                    "certificate-authority-data": base64.b64encode(ca_pem.encode()).decode(),
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
    binding_cache = config_overrides.pop("binding_cache", None)
    return AzureAksSubscriptionBindingDiscovery(
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AksSubscriptionDiscoveryConfig(
            management_endpoint="https://management.azure.com",
            management_audience="https://management.azure.com/.default",
            **config_overrides,
        ),
        binding_cache=binding_cache,
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
async def test_durable_binding_cache_skips_credential_call_for_unchanged_cluster() -> None:
    store = InMemoryStateStore()
    cache = StateStoreAksSubscriptionBindingCache(store)
    credential_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal credential_calls
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        _cluster(
                            _CLUSTER_ONE,
                            fqdn="aks-one.example",
                            etag="revision-one",
                        )
                    ]
                },
            )
        credential_calls += 1
        return httpx.Response(200, json=_credential(_CLUSTER_ONE))

    discovery = _discovery(handler, binding_cache=cache)
    first = await discovery.discover(_SUBSCRIPTION)
    second = await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert credential_calls == 1
    assert first.bindings[0].ca_pem == _CA
    assert first.bindings[0].ca_digest is not None
    assert second.bindings[0].ca_pem == _CA
    assert second.bindings[0].ca_digest == first.bindings[0].ca_digest
    record = await store.read_state(_cache_key(_CLUSTER_ONE))
    assert record is not None
    assert record["credential_material_retained"] is False
    assert record["ca_pem"] == _CA
    assert "kubeconfig" not in record
    assert "token" not in record
    assert "client-certificate-data" not in record
    assert "client-key-data" not in record
    assert "username" not in record


@pytest.mark.asyncio
async def test_cache_api_server_change_invalidates_before_use() -> None:
    store = InMemoryStateStore()
    cache = StateStoreAksSubscriptionBindingCache(store)
    fqdn = "aks-one.example"
    credential_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal credential_calls, fqdn
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        _cluster(_CLUSTER_ONE, fqdn=fqdn, etag="revision-one"),
                    ]
                },
            )
        credential_calls += 1
        return httpx.Response(200, json=_credential(_CLUSTER_ONE))

    discovery = _discovery(handler, binding_cache=cache)
    await discovery.discover(_SUBSCRIPTION)
    fqdn = "aks-one-recreated.example"
    await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert credential_calls == 2


@pytest.mark.asyncio
async def test_cache_revision_change_refreshes_ca_digest_before_reuse() -> None:
    store = InMemoryStateStore()
    cache = StateStoreAksSubscriptionBindingCache(store)
    etag = "revision-one"
    ca_pem = _CA
    credential_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal credential_calls, etag, ca_pem
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        _cluster(_CLUSTER_ONE, fqdn="aks-one.example", etag=etag),
                    ]
                },
            )
        credential_calls += 1
        return httpx.Response(200, json=_credential(_CLUSTER_ONE, ca_pem=ca_pem))

    discovery = _discovery(handler, binding_cache=cache)
    first = await discovery.discover(_SUBSCRIPTION)
    etag = "revision-two"
    ca_pem = "-----BEGIN CERTIFICATE-----\nY2hhbmdlZA==\n-----END CERTIFICATE-----\n"
    second = await discovery.discover(_SUBSCRIPTION)
    third = await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert credential_calls == 2
    assert first.bindings[0].ca_digest != second.bindings[0].ca_digest
    assert third.bindings[0].ca_pem == second.bindings[0].ca_pem
    assert third.bindings[0].ca_digest == second.bindings[0].ca_digest


@pytest.mark.asyncio
async def test_cache_ca_pem_digest_mismatch_forces_rediscovery() -> None:
    store = InMemoryStateStore()
    cache = StateStoreAksSubscriptionBindingCache(store)
    credential_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal credential_calls
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        _cluster(_CLUSTER_ONE, fqdn="aks-one.example", etag="revision-one"),
                    ]
                },
            )
        credential_calls += 1
        return httpx.Response(200, json=_credential(_CLUSTER_ONE))

    discovery = _discovery(handler, binding_cache=cache)
    first = await discovery.discover(_SUBSCRIPTION)
    retained = await store.read_state(_cache_key(_CLUSTER_ONE))
    assert retained is not None
    await store.write_state(
        _cache_key(_CLUSTER_ONE),
        {
            **retained,
            "ca_pem": "-----BEGIN CERTIFICATE-----\ndGFtcGVyZWQ=\n-----END CERTIFICATE-----\n",
        },
    )
    second = await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert credential_calls == 2
    assert first.bindings[0].ca_digest == second.bindings[0].ca_digest
    assert second.bindings[0].ca_pem == _CA


@pytest.mark.asyncio
async def test_cache_read_error_falls_back_to_fresh_discovery() -> None:
    class _BrokenCache:
        async def read(self, _cluster_ref: str) -> object:
            raise RuntimeError("cache unavailable")

        async def write(self, _binding: object) -> None:
            return None

    credential_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal credential_calls
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "value": [
                        _cluster(
                            _CLUSTER_ONE,
                            fqdn="aks-one.example",
                            etag="revision-one",
                        )
                    ]
                },
            )
        credential_calls += 1
        return httpx.Response(200, json=_credential(_CLUSTER_ONE))

    discovery = _discovery(handler, binding_cache=_BrokenCache())
    result = await discovery.discover(_SUBSCRIPTION)
    await discovery._http.aclose()

    assert credential_calls == 1
    assert result.bindings[0].ca_pem == _CA


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


@pytest.mark.parametrize(
    "private_flag,expected", [(True, 1), (False, 0), ("true", 0), (1, 0), (None, 0)]
)
async def test_explicit_private_mode_survives_unavailable_credentials(
    private_flag, expected
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            cluster = _cluster(_CLUSTER_ONE)
            cluster["properties"]["apiServerAccessProfile"] = {"enablePrivateCluster": private_flag}
            return httpx.Response(200, json={"value": [cluster]})
        return httpx.Response(403)

    discovery = _discovery(handler)
    try:
        result = await discovery.discover(_SUBSCRIPTION)
        assert len(result.private_clusters) == expected
        assert result.bindings == ()
        if expected:
            assert result.private_clusters[0].cluster_ref == _CLUSTER_ONE
            assert result.private_clusters[0].observed_at.tzinfo is not None
    finally:
        await discovery._http.aclose()


async def test_duplicate_private_cluster_rows_do_not_create_ambiguous_proposals() -> None:
    discovery = _discovery(
        lambda request: httpx.Response(
            200, json={"value": [_cluster(_CLUSTER_ONE), _cluster(_CLUSTER_ONE)]}
        )
    )
    try:
        with pytest.raises(AksSubscriptionDiscoveryError, match="duplicate"):
            await discovery.discover(_SUBSCRIPTION)
    finally:
        await discovery._http.aclose()


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
