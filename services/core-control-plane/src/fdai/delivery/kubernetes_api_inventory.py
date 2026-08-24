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

_MAX_OWNER_REFERENCES: Final[int] = 8
_MAX_LABELS: Final[int] = 128
_NODE_POOL_LABELS: Final[tuple[str, ...]] = (
    "kubernetes.azure.com/agentpool",
    "agentpool",
)
_RESOURCE_PATHS: Final[tuple[tuple[str, str, bool], ...]] = (
    ("/api/v1/namespaces", "kubernetes.namespace", False),
    ("/api/v1/nodes", "kubernetes.node", False),
    ("/api/v1/pods", "kubernetes.pod", True),
    ("/api/v1/services", "kubernetes.service", True),
    ("/api/v1/endpoints", "kubernetes.endpoints", True),
    ("/apis/batch/v1/jobs", "kubernetes.job", True),
    ("/apis/batch/v1/cronjobs", "kubernetes.cron-job", True),
    ("/apis/apps/v1/deployments", "kubernetes.deployment", True),
    ("/apis/apps/v1/replicasets", "kubernetes.replica-set", True),
    ("/apis/apps/v1/daemonsets", "kubernetes.daemon-set", True),
    ("/apis/apps/v1/statefulsets", "kubernetes.stateful-set", True),
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


__all__ = [
    "KubernetesApiAuth",
    "KubernetesApiInventoryConfig",
    "KubernetesApiInventoryError",
    "KubernetesApiInventorySnapshot",
    "KubernetesApiInventorySource",
    "ServiceAccountTokenAuth",
]
