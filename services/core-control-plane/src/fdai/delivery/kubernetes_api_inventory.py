"""Bounded Kubernetes API inventory source for runtime topology enrichment."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode, urlparse

import httpx

from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_OWNER_REFERENCES: Final[int] = 8
_MAX_LABELS: Final[int] = 128
_MAX_CONTAINER_STATUSES: Final[int] = 128
_MAX_CONDITIONS: Final[int] = 64
_MAX_INGRESS_BACKENDS: Final[int] = 128
_MAX_STATUS_TEXT: Final[int] = 128
_NODE_POOL_LABELS: Final[tuple[str, ...]] = (
    "kubernetes.azure.com/agentpool",
    "agentpool",
)
_AZURE_VMSS_VM_PROVIDER_PATH: Final[tuple[str, ...]] = (
    "subscriptions",
    "resourcegroups",
    "providers",
    "microsoft.compute",
    "virtualmachinescalesets",
    "virtualmachines",
)
_RESOURCE_PATHS: Final[tuple[tuple[str, str, bool], ...]] = (
    ("/api/v1/namespaces", "kubernetes.namespace", False),
    ("/api/v1/nodes", "kubernetes.node", False),
    ("/api/v1/pods", "kubernetes.pod", True),
    ("/api/v1/services", "kubernetes.service", True),
    ("/api/v1/endpoints", "kubernetes.endpoints", True),
    ("/apis/discovery.k8s.io/v1/endpointslices", "kubernetes.endpoint-slice", True),
    ("/apis/batch/v1/jobs", "kubernetes.job", True),
    ("/apis/batch/v1/cronjobs", "kubernetes.cron-job", True),
    ("/apis/apps/v1/deployments", "kubernetes.deployment", True),
    ("/apis/apps/v1/replicasets", "kubernetes.replica-set", True),
    ("/apis/apps/v1/daemonsets", "kubernetes.daemon-set", True),
    ("/apis/apps/v1/statefulsets", "kubernetes.stateful-set", True),
    ("/apis/networking.k8s.io/v1/ingresses", "kubernetes.ingress", True),
    ("/apis/networking.k8s.io/v1/ingressclasses", "kubernetes.ingress-class", False),
)


class KubernetesApiInventoryError(RuntimeError):
    """One Kubernetes inventory generation could not complete safely."""


class KubernetesApiAuth(Protocol):
    """Supply request headers without exposing credential material to inventory records."""

    async def headers(self) -> Mapping[str, str]: ...


@dataclass(frozen=True, slots=True)
class ServiceAccountTokenAuth:
    """Read a mounted service-account token only at request time."""

    token_path: Path

    async def headers(self) -> Mapping[str, str]:
        try:
            token = await asyncio.to_thread(self.token_path.read_text, encoding="utf-8")
        except OSError as exc:
            raise KubernetesApiInventoryError(
                "Kubernetes service-account token unavailable"
            ) from exc
        if not token.strip():
            raise KubernetesApiInventoryError("Kubernetes service-account token is empty")
        return {"Authorization": f"Bearer {token.strip()}", "Accept": "application/json"}


@dataclass(frozen=True, slots=True)
class WorkloadIdentityKubernetesAuth:
    """Acquire one short-lived Kubernetes audience token for each complete generation."""

    identity: WorkloadIdentity
    audience: str

    async def headers(self) -> Mapping[str, str]:
        if not self.audience.strip() or not self.audience.isascii():
            raise KubernetesApiInventoryError("Kubernetes workload audience is invalid")
        credential = await self.identity.get_token(self.audience)
        if credential.audience != self.audience or not credential.token.strip():
            raise KubernetesApiInventoryError("Kubernetes workload token is invalid")
        return {
            "Authorization": f"Bearer {credential.token.strip()}",
            "Accept": "application/json",
        }


@dataclass(frozen=True, slots=True)
class KubernetesApiInventoryConfig:
    """Bound one Kubernetes API endpoint to an exact ontology cluster identity."""

    api_server: str
    cluster_ref: str
    page_size: int = 500
    max_pages_per_resource: int = 64
    max_resources: int = 20_000
    max_response_bytes: int = 8 * 1024 * 1024
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_server)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Kubernetes api_server MUST be an absolute credential-free HTTPS URL")
        if not self.cluster_ref.strip() or len(self.cluster_ref) > 512:
            raise ValueError("Kubernetes cluster_ref MUST be bounded non-empty text")
        if not 1 <= self.page_size <= 5_000:
            raise ValueError("Kubernetes page_size MUST be in [1, 5000]")
        if (
            min(
                self.max_pages_per_resource,
                self.max_resources,
                self.max_response_bytes,
            )
            < 1
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Kubernetes inventory bounds MUST be positive")


@dataclass(frozen=True, slots=True)
class KubernetesApiInventorySnapshot:
    """One complete bounded Kubernetes runtime resource generation."""

    resources: tuple[ResourceRecord, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("Kubernetes inventory observed_at MUST be timezone-aware")
        identities = tuple(resource.resource_id for resource in self.resources)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("Kubernetes inventory resources MUST be unique and sorted")


class KubernetesApiInventorySource:
    """List reviewed core, apps, and batch resources under closed pagination bounds."""

    def __init__(
        self,
        *,
        config: KubernetesApiInventoryConfig,
        auth: KubernetesApiAuth,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._auth = auth
        self._http = http_client
        self._endpoint = urlparse(config.api_server)

    async def collect(self) -> KubernetesApiInventorySnapshot:
        """Return one complete UID-grounded generation or raise without partial output."""

        headers = await self._auth.headers()
        resources: dict[str, ResourceRecord] = {}
        observed_at = datetime.now(UTC)
        for path, resource_type, namespaced in _RESOURCE_PATHS:
            for item in await self._list(path, headers=headers):
                record = _resource_record(
                    item,
                    resource_type=resource_type,
                    namespaced=namespaced,
                    cluster_ref=self._config.cluster_ref,
                    observed_at=observed_at,
                )
                if record.resource_id in resources:
                    raise KubernetesApiInventoryError(
                        "Kubernetes inventory returned a duplicate resource UID"
                    )
                resources[record.resource_id] = record
                if len(resources) > self._config.max_resources:
                    raise KubernetesApiInventoryError("Kubernetes inventory resource cap exceeded")
        return KubernetesApiInventorySnapshot(
            resources=tuple(resources[key] for key in sorted(resources)),
            observed_at=observed_at,
        )

    async def _list(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
    ) -> tuple[Mapping[str, Any], ...]:
        items: list[Mapping[str, Any]] = []
        continuation = ""
        for _page in range(self._config.max_pages_per_resource):
            query = {"limit": str(self._config.page_size)}
            if continuation:
                query["continue"] = continuation
            url = f"{self._config.api_server.rstrip('/')}{path}?{urlencode(query)}"
            self._validate_url(url)
            try:
                response = await self._http.get(
                    url,
                    headers=dict(headers),
                    timeout=self._config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise KubernetesApiInventoryError("Kubernetes inventory request failed") from exc
            if response.status_code >= 400:
                raise KubernetesApiInventoryError(
                    f"Kubernetes inventory returned HTTP {response.status_code}"
                )
            if len(response.content) > self._config.max_response_bytes:
                raise KubernetesApiInventoryError("Kubernetes inventory response byte cap exceeded")
            try:
                payload = response.json()
            except ValueError as exc:
                raise KubernetesApiInventoryError(
                    "Kubernetes inventory response is not JSON"
                ) from exc
            if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
                raise KubernetesApiInventoryError("Kubernetes inventory response is missing items")
            for item in payload["items"]:
                if not isinstance(item, Mapping):
                    raise KubernetesApiInventoryError("Kubernetes inventory item is not an object")
                items.append(item)
            metadata = payload.get("metadata")
            raw_continue = metadata.get("continue", "") if isinstance(metadata, Mapping) else ""
            if not isinstance(raw_continue, str):
                raise KubernetesApiInventoryError(
                    "Kubernetes inventory continuation token is malformed"
                )
            continuation = raw_continue
            if not continuation:
                return tuple(items)
        raise KubernetesApiInventoryError("Kubernetes inventory pagination cap exceeded")

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != self._endpoint.netloc.casefold():
            raise KubernetesApiInventoryError("Kubernetes inventory URL changed scheme or host")


def _resource_record(
    item: Mapping[str, Any],
    *,
    resource_type: str,
    namespaced: bool,
    cluster_ref: str,
    observed_at: datetime,
) -> ResourceRecord:
    metadata = item.get("metadata")
    if not isinstance(metadata, Mapping):
        raise KubernetesApiInventoryError("Kubernetes resource metadata is missing")
    name = _required_text(metadata, "name")
    uid = _required_text(metadata, "uid")
    namespace = _required_text(metadata, "namespace") if namespaced else None
    labels = _string_mapping(metadata.get("labels"), limit=_MAX_LABELS)
    owner_uids = _owner_uids(metadata.get("ownerReferences"))
    props: dict[str, object] = {
        "cluster_ref": cluster_ref,
        "name": name,
        "uid": uid,
    }
    if namespace is not None:
        props["namespace"] = namespace
    elif resource_type == "kubernetes.namespace":
        props["namespace"] = name
    if labels:
        props["labels"] = labels
    if resource_type == "kubernetes.endpoint-slice":
        service_name = labels.get("kubernetes.io/service-name")
        if service_name:
            if len(service_name) > 253:
                raise KubernetesApiInventoryError(
                    "Kubernetes EndpointSlice Service label is malformed"
                )
            props["service_name"] = service_name
    if owner_uids:
        props["owner_uids"] = owner_uids
    spec = item.get("spec")
    if isinstance(spec, Mapping):
        selector = _string_mapping(spec.get("selector"), limit=_MAX_LABELS)
        if selector and resource_type == "kubernetes.service":
            props["selector"] = selector
        node_name = spec.get("nodeName")
        if resource_type == "kubernetes.pod" and isinstance(node_name, str) and node_name.strip():
            props["node_name"] = node_name.strip()
        if resource_type == "kubernetes.deployment":
            desired_replicas = _optional_non_negative_int(spec, "replicas")
            if desired_replicas is not None:
                props["desired_replicas"] = desired_replicas
        if resource_type == "kubernetes.node":
            provider_ref = _azure_vmss_vm_provider_ref(spec.get("providerID"))
            if provider_ref is not None:
                props["provider_resource_ref"] = provider_ref
        if resource_type == "kubernetes.ingress":
            backend_service_names = _ingress_backend_service_names(spec)
            if backend_service_names:
                props["backend_service_names"] = backend_service_names
            ingress_class_name = spec.get("ingressClassName")
            if isinstance(ingress_class_name, str) and ingress_class_name.strip():
                props["ingress_class_name"] = ingress_class_name.strip()
    status = item.get("status")
    if isinstance(status, Mapping):
        if resource_type == "kubernetes.pod":
            props.update(_pod_status_properties(status))
        elif resource_type == "kubernetes.deployment":
            props.update(_deployment_status_properties(status))
    if resource_type == "kubernetes.node":
        for label in _NODE_POOL_LABELS:
            node_pool = labels.get(label)
            if node_pool:
                props["node_pool"] = node_pool
                break
    namespace_key = namespace or "_cluster"
    digest = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:24]
    resource_id = f"{cluster_ref}/kubernetes/{resource_type}/{namespace_key}/{digest}"
    return ResourceRecord(
        resource_id=resource_id,
        type=resource_type,
        props=props,
        provider_ref=f"kubernetes-uid:{uid}",
        last_seen=observed_at.isoformat(),
    )


def _required_text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 512:
        raise KubernetesApiInventoryError(
            f"Kubernetes metadata {key!r} MUST be bounded non-empty text"
        )
    return raw.strip()


def _string_mapping(value: object, *, limit: int) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > limit:
        raise KubernetesApiInventoryError("Kubernetes string mapping exceeds its contract")
    output: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not isinstance(item, str)
            or not key.strip()
            or len(key) > 256
            or len(item) > 512
        ):
            raise KubernetesApiInventoryError("Kubernetes string mapping is malformed")
        output[key.strip()] = item.strip()
    return output


def _owner_uids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise KubernetesApiInventoryError("Kubernetes ownerReferences is malformed")
    if len(value) > _MAX_OWNER_REFERENCES:
        raise KubernetesApiInventoryError("Kubernetes ownerReferences exceeds its bound")
    uids = []
    for reference in value:
        if not isinstance(reference, Mapping):
            raise KubernetesApiInventoryError("Kubernetes owner reference is not an object")
        uid = _required_text(reference, "uid")
        uids.append(uid)
    if len(uids) != len(set(uids)):
        raise KubernetesApiInventoryError("Kubernetes owner reference UIDs MUST be unique")
    return tuple(uids)


def _azure_vmss_vm_provider_ref(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_048:
        return None
    parsed = urlparse(value.strip())
    if (
        parsed.scheme.casefold() != "azure"
        or parsed.netloc
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    path = "/" + parsed.path.strip("/")
    parts = tuple(part for part in path.split("/") if part)
    if len(parts) != 10:
        return None
    markers = tuple(parts[index].casefold() for index in (0, 2, 4, 5, 6, 8))
    if markers != _AZURE_VMSS_VM_PROVIDER_PATH:
        return None
    return path


def _ingress_backend_service_names(spec: Mapping[str, Any]) -> tuple[str, ...]:
    backends: list[object] = [spec.get("defaultBackend")]
    rules = _bounded_ingress_sequence(
        spec.get("rules"),
        field="Ingress rules",
    )
    for rule in rules:
        http = rule.get("http")
        if http is None:
            continue
        if not isinstance(http, Mapping):
            raise KubernetesApiInventoryError("Kubernetes Ingress HTTP rule is malformed")
        paths = _bounded_ingress_sequence(
            http.get("paths"),
            field="Ingress paths",
        )
        backends.extend(path.get("backend") for path in paths)
        if len(backends) > _MAX_INGRESS_BACKENDS:
            raise KubernetesApiInventoryError("Kubernetes Ingress backend cap exceeded")
    names: set[str] = set()
    for backend in backends:
        if backend is None:
            continue
        if not isinstance(backend, Mapping):
            raise KubernetesApiInventoryError("Kubernetes Ingress backend is malformed")
        service = backend.get("service")
        if not isinstance(service, Mapping):
            continue
        name = service.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 253:
            raise KubernetesApiInventoryError("Kubernetes Ingress Service name is malformed")
        names.add(name.strip())
    return tuple(sorted(names))


def _bounded_ingress_sequence(
    value: object,
    *,
    field: str,
) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > _MAX_INGRESS_BACKENDS
    ):
        raise KubernetesApiInventoryError(f"Kubernetes {field} exceeds its contract")
    if any(not isinstance(item, Mapping) for item in value):
        raise KubernetesApiInventoryError(f"Kubernetes {field} contains a malformed item")
    return tuple(item for item in value if isinstance(item, Mapping))


def _pod_status_properties(status: Mapping[str, Any]) -> dict[str, object]:
    props: dict[str, object] = {}
    phase = _optional_status_text(status, "phase")
    if phase is not None:
        props["phase"] = phase
    conditions = _bounded_mapping_sequence(
        status.get("conditions"),
        field="conditions",
        limit=_MAX_CONDITIONS,
    )
    ready_conditions = [
        condition for condition in conditions if _optional_status_text(condition, "type") == "Ready"
    ]
    if len(ready_conditions) > 1:
        raise KubernetesApiInventoryError("Kubernetes Pod Ready condition is duplicated")
    if ready_conditions:
        ready_status = _optional_status_text(ready_conditions[0], "status")
        if ready_status not in {"True", "False", "Unknown"}:
            raise KubernetesApiInventoryError("Kubernetes Pod Ready condition status is invalid")
        props["ready_status"] = ready_status
        if ready_status != "Unknown":
            props["ready"] = ready_status == "True"

    container_statuses = _bounded_mapping_sequence(
        status.get("containerStatuses"),
        field="containerStatuses",
        limit=_MAX_CONTAINER_STATUSES,
    )
    if container_statuses:
        ready_count = 0
        restart_count = 0
        waiting_reasons: list[str] = []
        for container_status in container_statuses:
            ready = container_status.get("ready")
            if not isinstance(ready, bool):
                raise KubernetesApiInventoryError(
                    "Kubernetes container ready status MUST be boolean"
                )
            ready_count += int(ready)
            restart_count += _required_non_negative_int(container_status, "restartCount")
            state = container_status.get("state")
            if state is not None and not isinstance(state, Mapping):
                raise KubernetesApiInventoryError("Kubernetes container state is malformed")
            waiting = state.get("waiting") if isinstance(state, Mapping) else None
            if waiting is not None and not isinstance(waiting, Mapping):
                raise KubernetesApiInventoryError("Kubernetes container waiting state is malformed")
            if isinstance(waiting, Mapping):
                reason = _optional_status_text(waiting, "reason")
                if reason is not None:
                    waiting_reasons.append(reason)
        props["container_count"] = len(container_statuses)
        props["ready_container_count"] = ready_count
        props["restart_count"] = restart_count
        if waiting_reasons:
            props["container_waiting_reasons"] = tuple(sorted(set(waiting_reasons)))
    return props


def _deployment_status_properties(status: Mapping[str, Any]) -> dict[str, object]:
    field_names = (
        ("observedGeneration", "observed_generation"),
        ("updatedReplicas", "updated_replicas"),
        ("readyReplicas", "ready_replicas"),
        ("availableReplicas", "available_replicas"),
        ("unavailableReplicas", "unavailable_replicas"),
    )
    props: dict[str, object] = {}
    for source_name, output_name in field_names:
        value = _optional_non_negative_int(status, source_name)
        if value is not None:
            props[output_name] = value
    conditions = _bounded_mapping_sequence(
        status.get("conditions"),
        field="conditions",
        limit=_MAX_CONDITIONS,
    )
    progressing_conditions = [
        condition
        for condition in conditions
        if _optional_status_text(condition, "type") == "Progressing"
    ]
    if len(progressing_conditions) > 1:
        raise KubernetesApiInventoryError(
            "Kubernetes Deployment Progressing condition is duplicated"
        )
    if progressing_conditions:
        progressing_status = _optional_status_text(progressing_conditions[0], "status")
        if progressing_status not in {"True", "False", "Unknown"}:
            raise KubernetesApiInventoryError(
                "Kubernetes Deployment Progressing condition status is invalid"
            )
        props["progressing_status"] = progressing_status
        progressing_reason = _optional_status_text(progressing_conditions[0], "reason")
        if progressing_reason is not None:
            props["progressing_reason"] = progressing_reason
    return props


def _bounded_mapping_sequence(
    value: object,
    *,
    field: str,
    limit: int,
) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > limit:
        raise KubernetesApiInventoryError(f"Kubernetes {field} exceeds its contract")
    if any(not isinstance(item, Mapping) for item in value):
        raise KubernetesApiInventoryError(f"Kubernetes {field} contains a malformed item")
    return tuple(item for item in value if isinstance(item, Mapping))


def _optional_status_text(value: Mapping[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw) > _MAX_STATUS_TEXT:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is malformed")
    return raw.strip()


def _optional_non_negative_int(value: Mapping[str, Any], key: str) -> int | None:
    raw = value.get(key)
    if raw is None:
        return None
    return _non_negative_int(raw, key)


def _required_non_negative_int(value: Mapping[str, Any], key: str) -> int:
    if key not in value:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is missing")
    return _non_negative_int(value[key], key)


def _non_negative_int(value: object, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KubernetesApiInventoryError(
            f"Kubernetes status {key!r} MUST be a non-negative integer"
        )
    return value


__all__ = [
    "KubernetesApiAuth",
    "KubernetesApiInventoryConfig",
    "KubernetesApiInventoryError",
    "KubernetesApiInventorySnapshot",
    "KubernetesApiInventorySource",
    "ServiceAccountTokenAuth",
    "WorkloadIdentityKubernetesAuth",
]
