"""Bounded Kubernetes API inventory source tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventoryConfig,
    KubernetesApiInventoryError,
    KubernetesApiInventorySource,
    WorkloadIdentityKubernetesAuth,
)
from fdai.shared.providers.workload_identity import IdentityToken

CLUSTER_REF = "scope-example/resource-group/rg-example/providers/containerservice/cluster-example"


class _Auth:
    async def headers(self) -> Mapping[str, str]:
        return {"Authorization": "Bearer test-token"}


class _Identity:
    def __init__(
        self,
        *,
        credential_value: str = "short-lived-value",
        audience: str = "aks-audience",
    ) -> None:
        self.credential_value = credential_value
        self.audience = audience
        self.requested: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.requested.append(audience)
        return IdentityToken(
            token=self.credential_value,
            audience=self.audience,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


async def test_workload_identity_auth_requests_exact_audience_without_persisting_token() -> None:
    identity = _Identity()

    headers = await WorkloadIdentityKubernetesAuth(
        identity=identity,
        audience="aks-audience",
    ).headers()

    assert identity.requested == ["aks-audience"]
    assert headers == {
        "Authorization": "Bearer short-lived-value",
        "Accept": "application/json",
    }


async def test_workload_identity_auth_rejects_wrong_audience_token() -> None:
    identity = _Identity(audience="wrong-audience")

    with pytest.raises(KubernetesApiInventoryError, match="workload token is invalid"):
        await WorkloadIdentityKubernetesAuth(
            identity=identity,
            audience="aks-audience",
        ).headers()


def _item(
    name: str,
    uid: str,
    *,
    namespace: str | None = None,
    labels: dict[str, str] | None = None,
    owner_uids: tuple[str, ...] = (),
    spec: dict[str, object] | None = None,
    status: dict[str, object] | None = None,
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
    if status is not None:
        result["status"] = status
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
                    spec={
                        "providerID": (
                            "azure:///subscriptions/subscription-example/resourceGroups/rg-example/"
                            "providers/Microsoft.Compute/virtualMachineScaleSets/vmss-example/"
                            "virtualMachines/0"
                        )
                    },
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
                    status={
                        "phase": "Pending",
                        "conditions": [{"type": "Ready", "status": "False"}],
                        "containerStatuses": [
                            {
                                "ready": False,
                                "restartCount": 2,
                                "state": {
                                    "waiting": {"reason": "ImagePullBackOff"},
                                },
                            }
                        ],
                    },
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
        elif request.url.path == "/apis/discovery.k8s.io/v1/endpointslices":
            items = [
                _item(
                    "api-abcd",
                    "uid-endpoint-slice",
                    namespace="default",
                    labels={"kubernetes.io/service-name": "api"},
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
            items = [
                _item(
                    "api",
                    "uid-deployment",
                    namespace="default",
                    spec={"replicas": 3},
                    status={
                        "observedGeneration": 7,
                        "updatedReplicas": 1,
                        "readyReplicas": 0,
                        "availableReplicas": 0,
                        "unavailableReplicas": 3,
                        "conditions": [
                            {
                                "type": "Progressing",
                                "status": "False",
                                "reason": "ProgressDeadlineExceeded",
                            }
                        ],
                    },
                )
            ]
        elif request.url.path == "/apis/networking.k8s.io/v1/ingresses":
            items = [
                _item(
                    "api",
                    "uid-ingress",
                    namespace="default",
                    spec={
                        "ingressClassName": "web",
                        "rules": [
                            {
                                "http": {
                                    "paths": [
                                        {"backend": {"service": {"name": "api"}}},
                                        {"backend": {"service": {"name": "health"}}},
                                    ]
                                }
                            }
                        ],
                    },
                )
            ]
        elif request.url.path == "/apis/networking.k8s.io/v1/ingressclasses":
            items = [_item("web", "uid-ingress-class")]
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

    assert len(requested_paths) == 14
    assert set(authorization_headers) == {"Bearer test-token"}
    by_type = {resource.type: resource for resource in snapshot.resources}
    assert by_type["kubernetes.namespace"].props["namespace"] == "default"
    assert by_type["kubernetes.node"].props["node_pool"] == "system"
    assert by_type["kubernetes.node"].props["provider_resource_ref"] == (
        "/subscriptions/subscription-example/resourceGroups/rg-example/providers/"
        "Microsoft.Compute/virtualMachineScaleSets/vmss-example/virtualMachines/0"
    )
    assert by_type["kubernetes.pod"].props["node_name"] == "node-1"
    assert by_type["kubernetes.pod"].props["owner_uids"] == ("uid-replica-set",)
    assert by_type["kubernetes.pod"].props["phase"] == "Pending"
    assert by_type["kubernetes.pod"].props["ready"] is False
    assert by_type["kubernetes.pod"].props["container_count"] == 1
    assert by_type["kubernetes.pod"].props["ready_container_count"] == 0
    assert by_type["kubernetes.pod"].props["restart_count"] == 2
    assert by_type["kubernetes.pod"].props["container_waiting_reasons"] == ("ImagePullBackOff",)
    assert by_type["kubernetes.service"].props["selector"] == {"app": "api"}
    assert by_type["kubernetes.endpoint-slice"].props["service_name"] == "api"
    assert by_type["kubernetes.ingress"].props["backend_service_names"] == (
        "api",
        "health",
    )
    assert by_type["kubernetes.ingress"].props["ingress_class_name"] == "web"
    assert by_type["kubernetes.deployment"].props["desired_replicas"] == 3
    assert by_type["kubernetes.deployment"].props["observed_generation"] == 7
    assert by_type["kubernetes.deployment"].props["updated_replicas"] == 1
    assert by_type["kubernetes.deployment"].props["ready_replicas"] == 0
    assert by_type["kubernetes.deployment"].props["available_replicas"] == 0
    assert by_type["kubernetes.deployment"].props["unavailable_replicas"] == 3
    assert by_type["kubernetes.deployment"].props["progressing_status"] == "False"
    assert (
        by_type["kubernetes.deployment"].props["progressing_reason"] == "ProgressDeadlineExceeded"
    )
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


async def test_rejects_malformed_endpoint_slice_service_label() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        items: list[dict[str, object]] = []
        if request.url.path == "/apis/discovery.k8s.io/v1/endpointslices":
            items = [
                _item(
                    "api-abcd",
                    "uid-endpoint-slice",
                    namespace="default",
                    labels={"kubernetes.io/service-name": "a" * 254},
                )
            ]
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
        with pytest.raises(KubernetesApiInventoryError, match="Service label is malformed"):
            await source.collect()


async def test_rollout_status_projection_rejects_malformed_container_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        items: list[dict[str, object]] = []
        if request.url.path == "/api/v1/pods":
            items = [
                _item(
                    "api-123",
                    "uid-pod",
                    namespace="default",
                    status={
                        "containerStatuses": [
                            {
                                "ready": "false",
                                "restartCount": -1,
                            }
                        ]
                    },
                )
            ]
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
        with pytest.raises(KubernetesApiInventoryError, match="ready status MUST be boolean"):
            await source.collect()


async def test_rollout_status_projection_omits_raw_image_and_message_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        items: list[dict[str, object]] = []
        if request.url.path == "/api/v1/pods":
            items = [
                _item(
                    "api-123",
                    "uid-pod",
                    namespace="default",
                    status={
                        "phase": "Pending",
                        "message": "provider-specific diagnostic text",
                        "containerStatuses": [
                            {
                                "image": "registry.example/workload:private-tag",
                                "imageID": "sha256:private-image-digest",
                                "ready": False,
                                "restartCount": 0,
                                "state": {
                                    "waiting": {
                                        "reason": "ErrImagePull",
                                        "message": "provider-specific pull failure",
                                    }
                                },
                            }
                        ],
                    },
                )
            ]
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

    pod = next(resource for resource in snapshot.resources if resource.type == "kubernetes.pod")
    assert pod.props["container_waiting_reasons"] == ("ErrImagePull",)
    assert "image" not in pod.props
    assert "image_id" not in pod.props
    assert "message" not in pod.props


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
