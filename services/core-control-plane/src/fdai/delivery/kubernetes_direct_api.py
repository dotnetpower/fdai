"""Exact-target Kubernetes direct-API adapter with server-side dry-run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiError,
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from fdai.shared.providers.state_store import StateStore

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
_LEDGER_PREFIX = "kubernetes-direct-api:idempotency:v1:"
_MAX_RESPONSE_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class KubernetesDirectApiConfig:
    """Credential-reference and target bounds for one exact cluster."""

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
            raise ValueError("Kubernetes API server must be an HTTPS origin")
        if not self.cluster_ref or len(self.cluster_ref) > 1024:
            raise ValueError("Kubernetes cluster_ref must be bounded non-empty text")
        if not self.allowed_namespaces or len(self.allowed_namespaces) > 32:
            raise ValueError("Kubernetes namespace allowlist must contain 1 to 32 items")
        if any(_NAME.fullmatch(namespace) is None for namespace in self.allowed_namespaces):
            raise ValueError("Kubernetes namespace allowlist contains an invalid name")
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("Kubernetes API timeout must be in [0.1, 120]")


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
    """Read a mounted service-account token and call one exact API origin."""

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
        token = (await asyncio.to_thread(self._config.token_path.read_text, "utf-8")).strip()
        if not token or len(token) > 16_384:
            raise DirectApiError("authentication", "Kubernetes token file is empty or invalid")
        params = {"dryRun": "All"} if dry_run else None
        async with httpx.AsyncClient(
            base_url=self._config.api_server,
            verify=str(self._config.ca_path),
            timeout=self._config.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.request(
                    method,
                    path,
                    params=params,
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
                raise DirectApiError("timeout", "Kubernetes API request timed out") from exc
            except httpx.RequestError as exc:
                raise DirectApiError("transport_error", "Kubernetes API request failed") from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise DirectApiError("response_limit", "Kubernetes API response exceeded its bound")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DirectApiError(
                "invalid_response",
                "Kubernetes API returned invalid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise DirectApiError("invalid_response", "Kubernetes API returned a non-object body")
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


class KubernetesMutationLedger(Protocol):
    """Retain one request fingerprint and successful receipt by idempotency key."""

    async def read(self, key: str) -> Mapping[str, object] | None: ...

    async def reserve(self, key: str, fingerprint: str) -> Mapping[str, object] | None: ...

    async def complete(self, key: str, value: Mapping[str, object]) -> None: ...


class StateStoreKubernetesMutationLedger:
    """Store Kubernetes idempotency receipts in the shared durable state store."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def read(self, key: str) -> Mapping[str, object] | None:
        return await self._store.read_state(f"{_LEDGER_PREFIX}{key}")

    async def reserve(self, key: str, fingerprint: str) -> Mapping[str, object] | None:
        value = {"fingerprint": fingerprint, "state": "reserved"}
        created = await self._store.write_state_if_absent(f"{_LEDGER_PREFIX}{key}", value)
        return None if created else await self.read(key)

    async def complete(self, key: str, value: Mapping[str, object]) -> None:
        existing = await self.read(key)
        if existing is None or existing.get("fingerprint") != value.get("fingerprint"):
            raise DirectApiPreconditionError(
                "Kubernetes idempotency reservation changed before completion"
            )
        await self._store.write_state(f"{_LEDGER_PREFIX}{key}", value)


class KubernetesDirectApiExecutor:
    """Execute exact Pod or Deployment operations after a server-side dry-run."""

    def __init__(
        self,
        *,
        config: KubernetesDirectApiConfig,
        ledger: KubernetesMutationLedger,
        transport: KubernetesApiTransport | None = None,
        fallback: DirectApiExecutor | None = None,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._transport = transport or HttpxKubernetesApiTransport(config)
        self._fallback = fallback

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Validate, dry-run, and optionally apply one exact Kubernetes mutation."""

        if not _is_kubernetes_request(request):
            if self._fallback is None:
                raise DirectApiPreconditionError("request is not an exact Kubernetes target")
            return await self._fallback.execute(request)
        if request.action_type_name not in KUBERNETES_ACTION_TYPES:
            raise DirectApiPreconditionError("Kubernetes action type is not registered")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError(
                "enforce-mode Kubernetes call requires an explicit enforce label"
            )
        operation = _operation(request, self._config)
        fingerprint = _fingerprint(request, operation)
        existing = await self._ledger.read(request.idempotency_key)
        if existing is not None:
            return _existing_receipt(existing, fingerprint)
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
                receipt_ref=f"kubernetes-dry-run:{fingerprint}",
                detail="Kubernetes server-side dry-run succeeded; no mutation submitted",
            )
        reserved = await self._ledger.reserve(request.idempotency_key, fingerprint)
        if reserved is not None:
            return _existing_receipt(reserved, fingerprint)
        applied = await self._transport.request(
            method=operation.method,
            path=operation.path,
            body=operation.body,
            dry_run=False,
        )
        receipt_ref = _receipt_ref(applied, operation.expected_identity)
        await self._ledger.complete(
            request.idempotency_key,
            {
                "fingerprint": fingerprint,
                "state": "completed",
                "receipt_ref": receipt_ref,
                "dry_run_ref": dry_run_ref,
            },
        )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=receipt_ref,
            detail="Kubernetes mutation accepted; independent effect verification remains required",
        )


@dataclass(frozen=True, slots=True)
class _KubernetesOperation:
    method: str
    path: str
    body: Mapping[str, object]
    expected_identity: str


def _is_kubernetes_request(request: DirectApiRequest) -> bool:
    return request.arguments.get("target_platform") == "kubernetes"


def _operation(
    request: DirectApiRequest,
    config: KubernetesDirectApiConfig,
) -> _KubernetesOperation:
    raw = request.arguments
    if raw.get("target_resource_ref") != request.resource_ref:
        raise DirectApiPreconditionError(
            "Kubernetes target_resource_ref must match the action resource_ref"
        )
    if raw.get("cluster_ref") != config.cluster_ref:
        raise DirectApiPreconditionError("Kubernetes cluster_ref does not match the bound cluster")
    namespace = _required(raw, "namespace", _NAMESPACE)
    if namespace not in config.allowed_namespaces:
        raise DirectApiPreconditionError("Kubernetes namespace is outside the configured allowlist")
    name = _required_name(raw, "resource_name")
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
        minimum_replicas = 0 if request.action_type_name == "ops.scale-in" else 1
        replicas = _integer(raw, "replica_count", minimum_replicas, 1000)
        return _KubernetesOperation(
            method="PUT",
            path=(f"/apis/apps/v1/namespaces/{encoded_namespace}/deployments/{encoded_name}/scale"),
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
        containers = _container_images(raw.get("container_images"))
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
                "spec": {"template": {"spec": {"containers": containers}}},
            },
            expected_identity=uid,
        )
    raise DirectApiPreconditionError("Kubernetes action type is not registered")


def _required_name(raw: Mapping[str, object], field: str) -> str:
    return _required(raw, field, _NAME)


def _required(raw: Mapping[str, object], field: str, pattern: re.Pattern[str]) -> str:
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
            f"Kubernetes {field} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _container_images(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Mapping) or not 1 <= len(value) <= 32:
        raise DirectApiPreconditionError(
            "Kubernetes rollback container_images must contain 1 to 32 entries"
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
                "Kubernetes rollback images must use valid names and digest-pinned references"
            )
        containers.append({"name": name, "image": image})
    return containers


def _fingerprint(request: DirectApiRequest, operation: _KubernetesOperation) -> str:
    canonical = json.dumps(
        {
            "action_type": request.action_type_name,
            "resource_ref": request.resource_ref,
            "method": operation.method,
            "path": operation.path,
            "body": operation.body,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _receipt_ref(response: KubernetesApiResponse, expected_identity: str) -> str:
    metadata = response.body.get("metadata")
    if isinstance(metadata, Mapping):
        uid = metadata.get("uid")
        if uid is not None and uid != expected_identity:
            raise DirectApiError("invalid_response", "Kubernetes response target identity changed")
    suffix = response.resource_version or expected_identity
    if not suffix or len(suffix) > 256:
        raise DirectApiError("invalid_response", "Kubernetes response omitted bounded identity")
    return f"kubernetes:{suffix}"


def _existing_receipt(
    existing: Mapping[str, object],
    fingerprint: str,
) -> DirectApiReceipt:
    if existing.get("fingerprint") != fingerprint:
        raise DirectApiPreconditionError(
            "Kubernetes idempotency key was reused with a different request"
        )
    if existing.get("state") == "reserved":
        raise DirectApiPreconditionError(
            "Kubernetes mutation has an unresolved prior reservation; reconcile before retry"
        )
    receipt_ref = existing.get("receipt_ref")
    if existing.get("state") != "completed" or not isinstance(receipt_ref, str) or not receipt_ref:
        raise DirectApiPreconditionError("Kubernetes idempotency receipt is malformed")
    return DirectApiReceipt(
        outcome=DirectApiOutcome.ALREADY_APPLIED,
        receipt_ref=receipt_ref,
        already_existed=True,
        detail="Kubernetes mutation already has a durable receipt",
    )


__all__ = [
    "KUBERNETES_ACTION_TYPES",
    "HttpxKubernetesApiTransport",
    "KubernetesApiResponse",
    "KubernetesApiTransport",
    "KubernetesDirectApiConfig",
    "KubernetesDirectApiExecutor",
    "KubernetesMutationLedger",
    "StateStoreKubernetesMutationLedger",
]
