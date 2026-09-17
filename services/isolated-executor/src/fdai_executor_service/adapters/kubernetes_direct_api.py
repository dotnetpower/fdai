"""Exact-target Kubernetes effects owned by the isolated Executor."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import quote, urlparse

import httpx
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    Mode,
)

KUBERNETES_ACTION_TYPES = frozenset(
    {
        "ops.restart-service",
        "ops.scale-in",
        "ops.scale-out",
        "ops.rollback-kubernetes-rollout",
    }
)
_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?$")
_NAMESPACE = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_UID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_RESOURCE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DIGEST_PINNED_IMAGE = re.compile(r"^[^\s@]{1,430}@sha256:[a-f0-9]{64}$")
_MAX_RESPONSE_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class KubernetesDirectApiConfig:
    """Credential references and target bounds for one exact cluster."""

    api_server: str
    cluster_ref: str
    token_path: Path
    ca_path: Path
    allowed_namespaces: frozenset[str]
    timeout_seconds: float = 30

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_server)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Kubernetes API server MUST be an HTTPS origin")
        if not self.cluster_ref or len(self.cluster_ref) > 1024:
            raise ValueError("Kubernetes cluster_ref MUST be bounded non-empty text")
        if not self.allowed_namespaces or len(self.allowed_namespaces) > 32:
            raise ValueError("Kubernetes namespace allowlist MUST contain 1 to 32 items")
        if any(_NAMESPACE.fullmatch(namespace) is None for namespace in self.allowed_namespaces):
            raise ValueError("Kubernetes namespace allowlist contains an invalid name")
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("Kubernetes API timeout MUST be in [0.1, 120]")


@dataclass(frozen=True, slots=True)
class KubernetesApiResponse:
    """Bounded response metadata retained by the adapter."""

    status_code: int
    body: Mapping[str, object]
    resource_version: str | None


class KubernetesApiTransport(Protocol):
    """Send one internally constructed Kubernetes API request."""

    async def request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, object],
        dry_run: bool,
    ) -> KubernetesApiResponse: ...


class HttpxKubernetesApiTransport:
    """Read the projected ServiceAccount token and call one exact API origin."""

    def __init__(self, config: KubernetesDirectApiConfig) -> None:
        self._config = config

    async def request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, object],
        dry_run: bool,
    ) -> KubernetesApiResponse:
        try:
            token = (
                await asyncio.to_thread(self._config.token_path.read_text, encoding="utf-8")
            ).strip()
        except OSError as exc:
            raise DirectApiAuthenticationError("Kubernetes token file is unavailable") from exc
        if not token or len(token) > 16_384:
            raise DirectApiAuthenticationError("Kubernetes token file is empty or invalid")
        try:
            async with httpx.AsyncClient(
                base_url=self._config.api_server,
                verify=str(self._config.ca_path),
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params={"dryRun": "All"} if dry_run else None,
                    headers={
                        "authorization": f"Bearer {token}",
                        "accept": "application/json",
                        "content-type": (
                            "application/strategic-merge-patch+json"
                            if method == "PATCH"
                            else "application/json"
                        ),
                    },
                    json=dict(body),
                )
        except httpx.TimeoutException as exc:
            raise DirectApiError(
                "provider_outcome_unknown",
                "Kubernetes API request timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise DirectApiError("transport_error", "Kubernetes API request failed") from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise DirectApiError("response_limit", "Kubernetes API response exceeded its bound")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DirectApiError(
                "invalid_response", "Kubernetes API returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise DirectApiError("invalid_response", "Kubernetes API returned a non-object body")
        if response.status_code == 401:
            raise DirectApiAuthenticationError("Kubernetes API rejected authentication")
        if response.status_code == 403:
            raise DirectApiPermissionDeniedError("Kubernetes API denied the requested action")
        if response.status_code in {409, 422}:
            raise DirectApiPreconditionError("Kubernetes target precondition changed")
        if response.status_code < 200 or response.status_code >= 300:
            reason = str(payload.get("reason") or "api_error")
            raise DirectApiError(
                "provider_error",
                f"Kubernetes API rejected the request with {response.status_code}:{reason}",
            )
        metadata = payload.get("metadata")
        resource_version = (
            str(metadata.get("resourceVersion"))
            if isinstance(metadata, Mapping) and metadata.get("resourceVersion") is not None
            else None
        )
        return KubernetesApiResponse(
            status_code=response.status_code,
            body=payload,
            resource_version=resource_version,
        )


class KubernetesDirectApiExecutor:
    """Server-dry-run and apply one registered exact Kubernetes action."""

    def __init__(
        self,
        *,
        config: KubernetesDirectApiConfig,
        transport: KubernetesApiTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or HttpxKubernetesApiTransport(config)

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name not in KUBERNETES_ACTION_TYPES:
            raise DirectApiPreconditionError("Kubernetes action type is not registered")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError(
                "enforce-mode Kubernetes call requires an explicit enforce label"
            )
        operation = _operation(request, self._config)
        dry_run = await self._transport.request(
            method=operation.method,
            path=operation.path,
            body=operation.body,
            dry_run=True,
        )
        dry_run_ref = _receipt_ref(dry_run, operation.expected_identity)
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"kubernetes-dry-run:{dry_run_ref}",
                detail="Kubernetes server-side dry-run succeeded; no mutation submitted",
            )
        applied = await self._transport.request(
            method=operation.method,
            path=operation.path,
            body=operation.body,
            dry_run=False,
        )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=_receipt_ref(applied, operation.expected_identity),
            detail="Kubernetes mutation accepted; independent effect verification remains required",
        )


@runtime_checkable
class _OperationStatusReader(Protocol):
    async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None: ...


class KubernetesDirectApiRouter:
    """Route registered Kubernetes actions before an optional provider fallback."""

    def __init__(
        self,
        kubernetes: DirectApiExecutor,
        fallback: DirectApiExecutor | None,
    ) -> None:
        self._kubernetes = kubernetes
        self._fallback = fallback

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name in KUBERNETES_ACTION_TYPES:
            return await self._kubernetes.execute(request)
        if self._fallback is None:
            raise DirectApiPreconditionError("direct-API action has no isolated Executor adapter")
        return await self._fallback.execute(request)

    async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None:
        if request.action_type_name in KUBERNETES_ACTION_TYPES:
            return None
        if isinstance(self._fallback, _OperationStatusReader):
            return await self._fallback.operation_status(request)
        return None


@dataclass(frozen=True, slots=True)
class _KubernetesOperation:
    method: str
    path: str
    body: Mapping[str, object]
    expected_identity: str


def _operation(
    request: DirectApiRequest,
    config: KubernetesDirectApiConfig,
) -> _KubernetesOperation:
    raw = request.arguments
    if raw.get("target_resource_ref") != request.resource_ref:
        raise DirectApiPreconditionError(
            "Kubernetes target_resource_ref MUST match the action resource_ref"
        )
    if raw.get("cluster_ref") != config.cluster_ref:
        raise DirectApiPreconditionError("Kubernetes cluster_ref does not match the bound cluster")
    namespace = _required(raw, "namespace", _NAMESPACE)
    if namespace not in config.allowed_namespaces:
        raise DirectApiPreconditionError("Kubernetes namespace is outside the configured allowlist")
    name = _required(raw, "resource_name", _NAME)
    uid = _required(raw, "target_uid", _UID)
    resource_version = _required(raw, "resource_version", _RESOURCE_VERSION)
    encoded_namespace = quote(namespace, safe="")
    encoded_name = quote(name, safe="")
    if request.action_type_name == "ops.restart-service":
        if raw.get("target_kind") != "Pod":
            raise DirectApiPreconditionError("Kubernetes restart requires target_kind=Pod")
        return _KubernetesOperation(
            method="DELETE",
            path=f"/api/v1/namespaces/{encoded_namespace}/pods/{encoded_name}",
            body={
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "gracePeriodSeconds": _integer(raw, "grace_period_seconds", 0, 300, default=30),
                "preconditions": {"uid": uid, "resourceVersion": resource_version},
            },
            expected_identity=uid,
        )
    if request.action_type_name in {"ops.scale-in", "ops.scale-out"}:
        if raw.get("target_kind") != "Deployment":
            raise DirectApiPreconditionError("Kubernetes scale requires target_kind=Deployment")
        replicas = _integer(
            raw,
            "replica_count",
            0 if request.action_type_name == "ops.scale-in" else 1,
            1000,
        )
        return _KubernetesOperation(
            method="PUT",
            path=f"/apis/apps/v1/namespaces/{encoded_namespace}/deployments/{encoded_name}/scale",
            body={
                "apiVersion": "autoscaling/v1",
                "kind": "Scale",
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "uid": uid,
                    "resourceVersion": resource_version,
                },
                "spec": {"replicas": replicas},
            },
            expected_identity=uid,
        )
    if request.action_type_name == "ops.rollback-kubernetes-rollout":
        if raw.get("target_kind") != "Deployment":
            raise DirectApiPreconditionError("Kubernetes rollback requires target_kind=Deployment")
        return _KubernetesOperation(
            method="PATCH",
            path=f"/apis/apps/v1/namespaces/{encoded_namespace}/deployments/{encoded_name}",
            body={
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "uid": uid,
                    "resourceVersion": resource_version,
                },
                "spec": {"template": {"spec": {"containers": _container_images(raw)}}},
            },
            expected_identity=uid,
        )
    raise DirectApiPreconditionError("Kubernetes action type is not registered")


def _required(
    raw: Mapping[str, object],
    field: str,
    pattern: re.Pattern[str],
) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise DirectApiPreconditionError(f"Kubernetes {field} is invalid")
    return value


def _integer(
    raw: Mapping[str, object],
    field: str,
    minimum: int,
    maximum: int,
    *,
    default: int | None = None,
) -> int:
    value = raw.get(field, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise DirectApiPreconditionError(
            f"Kubernetes {field} MUST be an integer in [{minimum}, {maximum}]"
        )
    return value


def _container_images(raw: Mapping[str, object]) -> list[dict[str, str]]:
    value = raw.get("container_images")
    if not isinstance(value, Mapping) or not 1 <= len(value) <= 32:
        raise DirectApiPreconditionError(
            "Kubernetes rollback container_images MUST contain 1 to 32 entries"
        )
    containers: list[dict[str, str]] = []
    for name, image in sorted(value.items(), key=lambda item: str(item[0])):
        if (
            not isinstance(name, str)
            or _NAME.fullmatch(name) is None
            or not isinstance(image, str)
            or _DIGEST_PINNED_IMAGE.fullmatch(image) is None
        ):
            raise DirectApiPreconditionError(
                "Kubernetes rollback images MUST use valid names and digest-pinned references"
            )
        containers.append({"name": name, "image": image})
    return containers


def _receipt_ref(response: KubernetesApiResponse, expected_identity: str) -> str:
    encoded = json.dumps(
        {
            "identity": expected_identity,
            "resource_version": response.resource_version,
            "status_code": response.status_code,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"kubernetes:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "HttpxKubernetesApiTransport",
    "KUBERNETES_ACTION_TYPES",
    "KubernetesApiResponse",
    "KubernetesApiTransport",
    "KubernetesDirectApiConfig",
    "KubernetesDirectApiExecutor",
    "KubernetesDirectApiRouter",
]
