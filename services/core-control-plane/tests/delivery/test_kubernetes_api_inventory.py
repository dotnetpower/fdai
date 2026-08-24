"""Bounded Kubernetes API inventory source tests."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventoryConfig,
    KubernetesApiInventoryError,
    KubernetesApiInventorySource,
)

CLUSTER_REF = "scope-example/resource-group/rg-example/providers/containerservice/cluster-example"


class _Auth:
    async def headers(self) -> Mapping[str, str]:
        return {"Authorization": "Bearer test-token"}


def _item(
    name: str,
    uid: str,
    *,
    namespace: str | None = None,
    labels: dict[str, str] | None = None,
    owner_uids: tuple[str, ...] = (),
    spec: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {"name": name, "uid": uid}
    if namespace is not None:
        metadata["namespace"] = namespace
    if labels is not None:
        metadata["labels"] = labels
    if owner_uids:
        metadata["ownerReferences"] = [{"uid": uid} for uid in owner_uids]
    result: dict[str, object] = {"metadata": metadata}
    if spec is not None:
        result["spec"] = spec
    return result


async def test_collects_uid_grounded_runtime_inventory() -> None:
    requested_paths: list[str] = []
    authorization_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        authorization_headers.append(request.headers.get("Authorization"))
        items: list[dict[str, object]] = []
        if request.url.path == "/api/v1/namespaces":
            items = [_item("default", "uid-namespace")]
        elif request.url.path == "/api/v1/nodes":
            items = [
                _item(
                    "node-1",
                    "uid-node",
                    labels={"kubernetes.azure.com/agentpool": "system"},
                )
            ]
        elif request.url.path == "/api/v1/pods":
            items = [
                _item(
                    "api-123",
                    "uid-pod",
                    namespace="default",
                    owner_uids=("uid-replica-set",),
                    spec={"nodeName": "node-1"},
                )
            ]
        elif request.url.path == "/api/v1/services":
            items = [
                _item(
                    "api",
                    "uid-service",
                    namespace="default",
                    spec={"selector": {"app": "api"}},
                )
            ]
        elif request.url.path == "/apis/apps/v1/replicasets":
            items = [
                _item(
                    "api-123",
                    "uid-replica-set",
                    namespace="default",
                    owner_uids=("uid-deployment",),
                )
            ]
        elif request.url.path == "/apis/apps/v1/deployments":
            items = [_item("api", "uid-deployment", namespace="default")]
        return httpx.Response(200, json={"items": items, "metadata": {"continue": ""}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(
                api_server="https://kubernetes.example",
                cluster_ref=CLUSTER_REF,
            ),
            auth=_Auth(),
            http_client=client,
        )
        snapshot = await source.collect()

    assert len(requested_paths) == 11
    assert set(authorization_headers) == {"Bearer test-token"}
    by_type = {resource.type: resource for resource in snapshot.resources}
    assert by_type["kubernetes.namespace"].props["namespace"] == "default"
    assert by_type["kubernetes.node"].props["node_pool"] == "system"
    assert by_type["kubernetes.pod"].props["node_name"] == "node-1"
    assert by_type["kubernetes.pod"].props["owner_uids"] == ("uid-replica-set",)
    assert by_type["kubernetes.service"].props["selector"] == {"app": "api"}
    assert all(resource.resource_id.startswith(CLUSTER_REF) for resource in snapshot.resources)
    assert all(
        resource.provider_ref.startswith("kubernetes-uid:")
        for resource in snapshot.resources
        if resource.provider_ref
    )


async def test_rejects_partial_resource_family_without_returning_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/pods":
            return httpx.Response(403, json={"message": "forbidden"})
        return httpx.Response(200, json={"items": [], "metadata": {"continue": ""}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(
                api_server="https://kubernetes.example",
                cluster_ref=CLUSTER_REF,
            ),
            auth=_Auth(),
            http_client=client,
        )
        with pytest.raises(KubernetesApiInventoryError, match="HTTP 403"):
            await source.collect()


async def test_rejects_pagination_beyond_bound() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"items": [], "metadata": {"continue": "next-page"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(
                api_server="https://kubernetes.example",
                cluster_ref=CLUSTER_REF,
                max_pages_per_resource=1,
            ),
            auth=_Auth(),
            http_client=client,
        )
        with pytest.raises(KubernetesApiInventoryError, match="pagination cap"):
            await source.collect()
