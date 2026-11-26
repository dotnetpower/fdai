"""Bounded read-only Kubernetes snapshots for an exact order-acceptance target."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import ssl
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from fdai.delivery.kubernetes_api_inventory import KubernetesApiAuth

from fdai_aks_commerce.acceptance import OrderAcceptanceIntent


@dataclass(frozen=True, slots=True)
class AcceptanceKubernetesSnapshot:
    """Payload-free resource observation; no maintenance, authorization or effect conclusion."""

    deployment_uid: str
    resource_version: str
    service_uid: str
    desired_replicas: int
    ready_replicas: int
    ready_endpoints: int
    hpa_managed: bool
    observed_at: datetime
    cluster_ref: str
    resource_ref: str
    service_resource_ref: str
    namespace: str

    def evidence_ref(self) -> str:
        """Bind normalized values and completion time without retaining provider payloads."""
        payload = {**asdict(self), "observed_at": self.observed_at.isoformat()}
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )


class KubernetesOrderAcceptanceReader:
    """Read only a configured Deployment and its Service path, holding on partial or raced reads."""

    def __init__(
        self,
        *,
        api_server: str,
        intent: OrderAcceptanceIntent,
        service_name: str,
        service_uid: str,
        auth: KubernetesApiAuth,
        tls: ssl.SSLContext,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        parsed = urlparse(api_server)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("acceptance Kubernetes API must be an exact HTTPS origin")
        if re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", service_name) is None:
            raise ValueError("acceptance Service name must be an exact DNS label")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", service_uid) is None:
            raise ValueError("acceptance Service UID is invalid")
        if not tls.check_hostname or tls.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("acceptance Kubernetes TLS verification must remain enabled")
        self._api_server = api_server
        self._intent = intent
        self._service_name = service_name
        self._service_uid = service_uid
        self._auth = auth
        self._tls = tls
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read(self) -> AcceptanceKubernetesSnapshot:
        """Read one GET-only snapshot within five seconds; missing status remains unknown."""
        intent = self._intent
        namespace = quote(intent.namespace, safe="")
        deployment_path = (
            f"/apis/apps/v1/namespaces/{namespace}/deployments/{intent.deployment_name}"
        )
        service_path = f"/api/v1/namespaces/{namespace}/services/{self._service_name}"
        async with (
            asyncio.timeout(5),
            httpx.AsyncClient(
                base_url=self._api_server,
                verify=self._tls,
                timeout=3,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client,
        ):
            deployment = await self._get(client, deployment_path)
            _identity(
                deployment,
                "Deployment",
                intent.namespace,
                intent.deployment_name,
                intent.deployment_uid,
            )
            status = _object(deployment.get("status"))
            metadata = _object(deployment.get("metadata"))
            spec = _object(deployment.get("spec"))
            generation = _count(metadata.get("generation"))
            if _count(status.get("observedGeneration")) != generation:
                raise ValueError("acceptance Deployment generation is not observed")
            desired = _count(spec.get("replicas"))
            ready = _count(status.get("readyReplicas", 0))
            version = metadata.get("resourceVersion")
            if not isinstance(version, str) or not version or len(version) > 256:
                raise ValueError("acceptance Deployment resource version is unavailable")
            service = await self._get(client, service_path)
            _identity(service, "Service", intent.namespace, self._service_name, self._service_uid)
            selector = _object(_object(service.get("spec")).get("selector"))
            labels = _object(_object(_object(spec.get("template")).get("metadata")).get("labels"))
            if not selector or any(labels.get(key) != value for key, value in selector.items()):
                raise ValueError("acceptance Service does not select the bound Deployment")
            slices = _items(
                await self._get(
                    client,
                    f"/apis/discovery.k8s.io/v1/namespaces/{namespace}/endpointslices",
                    {
                        "labelSelector": f"kubernetes.io/service-name={self._service_name}",
                        "limit": "100",
                    },
                )
            )
            ready_endpoints = await self._endpoints(client, slices, namespace)
            hpas = _items(
                await self._get(
                    client,
                    f"/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers",
                    {"limit": "100"},
                )
            )
            hpa_managed = any(
                _object(_object(hpa.get("spec")).get("scaleTargetRef")).get("kind") == "Deployment"
                and _object(_object(hpa.get("spec")).get("scaleTargetRef")).get("name")
                == intent.deployment_name
                for hpa in hpas
            )
            final = await self._get(client, deployment_path)
            _identity(
                final, "Deployment", intent.namespace, intent.deployment_name, intent.deployment_uid
            )
            final_service = await self._get(client, service_path)
            _identity(
                final_service, "Service", intent.namespace, self._service_name, self._service_uid
            )
            if _object(final.get("metadata")).get("resourceVersion") != version or _object(
                final_service.get("metadata")
            ).get("resourceVersion") != _object(service.get("metadata")).get("resourceVersion"):
                raise ValueError("acceptance target changed during observation")
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("acceptance observation clock must be timezone-aware")
        return AcceptanceKubernetesSnapshot(
            intent.deployment_uid,
            version,
            self._service_uid,
            desired,
            ready,
            ready_endpoints,
            hpa_managed,
            observed_at,
            intent.cluster_ref,
            intent.resource_ref,
            intent.service_resource_ref,
            intent.namespace,
        )

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        async with client.stream(
            "GET", path, params=params, headers=await self._auth.headers()
        ) as response:
            if response.status_code != 200:
                raise ValueError("acceptance Kubernetes observation is unavailable")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 262_144:
                    raise ValueError("acceptance Kubernetes response exceeds its bound")
        return _object(json.loads(content))

    async def _endpoints(
        self,
        client: httpx.AsyncClient,
        slices: list[dict[str, Any]],
        namespace: str,
    ) -> int:
        seen: set[str] = set()
        for item in slices:
            metadata = _object(item.get("metadata"))
            if (
                item.get("kind") != "EndpointSlice"
                or metadata.get("namespace") != self._intent.namespace
                or _object(metadata.get("labels")).get("kubernetes.io/service-name")
                != self._service_name
                or _controller(metadata, "Service") != self._service_uid
            ):
                raise ValueError("acceptance EndpointSlice ownership does not match")
            endpoints = item.get("endpoints")
            if not isinstance(endpoints, list) or len(endpoints) > 100:
                raise ValueError("acceptance EndpointSlice is incomplete")
            for endpoint in endpoints:
                conditions = _object(_object(endpoint).get("conditions"))
                if type(conditions.get("ready")) is not bool:
                    raise ValueError("acceptance endpoint readiness is unknown")
                if conditions["ready"] is False or conditions.get("terminating") is True:
                    continue
                target = _object(_object(endpoint).get("targetRef"))
                if target.get("kind") != "Pod" or target.get("namespace") != self._intent.namespace:
                    raise ValueError("acceptance endpoint Pod identity is unavailable")
                name = _name(target.get("name"))
                uid = target.get("uid")
                if not isinstance(uid, str) or not uid:
                    raise ValueError("acceptance endpoint Pod UID is unavailable")
                if uid in seen:
                    continue
                if len(seen) >= 16:
                    raise ValueError("acceptance endpoint verification exceeds its bound")
                pod = await self._get(client, f"/api/v1/namespaces/{namespace}/pods/{name}")
                _identity(pod, "Pod", self._intent.namespace, name, uid)
                owners = _object(pod.get("metadata"))
                replica_uid = _controller(owners, "ReplicaSet")
                replica_name = _name(
                    next(
                        owner["name"]
                        for owner in owners["ownerReferences"]
                        if owner.get("controller") is True and owner.get("kind") == "ReplicaSet"
                    )
                )
                replica = await self._get(
                    client, f"/apis/apps/v1/namespaces/{namespace}/replicasets/{replica_name}"
                )
                _identity(replica, "ReplicaSet", self._intent.namespace, replica_name, replica_uid)
                if (
                    _controller(_object(replica.get("metadata")), "Deployment")
                    != self._intent.deployment_uid
                ):
                    raise ValueError("acceptance endpoint belongs to another Deployment")
                pod_conditions = _object(pod.get("status")).get("conditions")
                if not isinstance(pod_conditions, list) or not any(
                    _object(condition).get("type") == "Ready"
                    and _object(condition).get("status") == "True"
                    for condition in pod_conditions
                ):
                    raise ValueError("acceptance endpoint Pod is not ready")
                seen.add(uid)
        return len(seen)


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("acceptance Kubernetes response contains an invalid object")
    return value


def _count(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("acceptance Kubernetes count is unknown")
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", value) is None:
        raise ValueError("acceptance Kubernetes resource name is invalid")
    return value


def _identity(value: dict[str, Any], kind: str, namespace: str, name: str, uid: str) -> None:
    metadata = _object(value.get("metadata"))
    if (
        value.get("kind") != kind
        or metadata.get("namespace") != namespace
        or metadata.get("name") != name
        or metadata.get("uid") != uid
    ):
        raise ValueError("acceptance Kubernetes target identity changed")


def _items(value: dict[str, Any]) -> list[dict[str, Any]]:
    if _object(value.get("metadata")).get("continue"):
        raise ValueError("acceptance Kubernetes list is truncated")
    items = value.get("items")
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("acceptance Kubernetes list is incomplete")
    return [_object(item) for item in items]


def _controller(metadata: dict[str, Any], kind: str) -> str:
    owners = metadata.get("ownerReferences")
    if not isinstance(owners, list):
        raise ValueError("acceptance Kubernetes ownership is unavailable")
    matches = [_object(owner) for owner in owners if _object(owner).get("controller") is True]
    if len(matches) != 1 or matches[0].get("kind") != kind or not matches[0].get("uid"):
        raise ValueError("acceptance Kubernetes controller is ambiguous")
    return str(matches[0]["uid"])
