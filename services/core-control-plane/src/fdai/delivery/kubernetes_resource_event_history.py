"""Bounded Kubernetes Event history for secured Resource collections."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.core.ontology_platform.resource_event_queries import (
    KUBERNETES_EVENT_FAMILY,
    ResourceEventCollection,
    ResourceEventObservation,
)
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiAuth,
    kubernetes_resource_id,
)

_MAX_EVENTS: Final = 256
_MAX_RESPONSE_BYTES: Final = 262_144
_KIND_TO_RESOURCE_TYPE: Final[dict[str, tuple[str, bool]]] = {
    "CronJob": ("kubernetes.cron-job", True),
    "DaemonSet": ("kubernetes.daemon-set", True),
    "Deployment": ("kubernetes.deployment", True),
    "EndpointSlice": ("kubernetes.endpoint-slice", True),
    "Endpoints": ("kubernetes.endpoints", True),
    "Ingress": ("kubernetes.ingress", True),
    "IngressClass": ("kubernetes.ingress-class", False),
    "Job": ("kubernetes.job", True),
    "Namespace": ("kubernetes.namespace", False),
    "Node": ("kubernetes.node", False),
    "Pod": ("kubernetes.pod", True),
    "ReplicaSet": ("kubernetes.replica-set", True),
    "Service": ("kubernetes.service", True),
    "StatefulSet": ("kubernetes.stateful-set", True),
}


class KubernetesResourceEventHistoryError(RuntimeError):
    """Report a bounded Kubernetes Event read failure without provider content."""


@dataclass(frozen=True, slots=True)
class KubernetesResourceEventHistoryConfig:
    """Bind one credential-free API endpoint to an exact cluster Resource."""

    api_server: str
    cluster_ref: str
    ca_path: Path | None = None
    ca_pem: str | None = None
    timeout_seconds: float = 10.0
    max_response_bytes: int = _MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_server)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Kubernetes event api_server MUST be credential-free HTTPS")
        if not self.cluster_ref.strip() or len(self.cluster_ref) > 512:
            raise ValueError("Kubernetes event cluster_ref MUST be bounded non-empty text")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("Kubernetes event timeout_seconds MUST be in [0.1, 30]")
        if not 1_024 <= self.max_response_bytes <= _MAX_RESPONSE_BYTES:
            raise ValueError("Kubernetes event max_response_bytes MUST be in [1024, 262144]")
        if self.ca_path is not None and self.ca_pem is not None:
            raise ValueError("Kubernetes event reader accepts exactly one CA binding")


@dataclass(frozen=True, slots=True)
class _ParsedEvent:
    event: ResourceEventObservation | None
    malformed: bool = False


class KubernetesResourceEventHistoryReader:
    """Read normalized Kubernetes Events under exact Resource or cluster scope."""

    def __init__(
        self,
        *,
        auth: KubernetesApiAuth,
        config: KubernetesResourceEventHistoryConfig,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._auth: Final = auth
        self._config: Final = config
        self._client_factory: Final = client_factory
        self._now: Final = now or (lambda: datetime.now(UTC))

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        """Return chronological normalized Events or an explicit limitation."""

        return await self._read_history(
            resource_ids=resource_ids,
            resource_identity=None,
            event_families=event_families,
            lookback_seconds=lookback_seconds,
        )

    async def read_history_with_identity(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        """Narrow one exact child read with receipt-bound Kubernetes identity."""

        return await self._read_history(
            resource_ids=resource_ids,
            resource_identity=resource_identity,
            event_families=event_families,
            lookback_seconds=lookback_seconds,
        )

    async def _read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]] | None,
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:

        if event_families != (KUBERNETES_EVENT_FAMILY,):
            raise ValueError("Kubernetes event reader received an unsupported family")
        if not 60 <= lookback_seconds <= 86_400:
            raise ValueError("Resource event lookback_seconds MUST be in [60, 86400]")
        requested = tuple(sorted(set(resource_ids)))
        if requested != resource_ids or not requested or len(requested) > 1000:
            raise ValueError("Resource event resource_ids MUST be ordered within the server bound")
        cluster_child_prefix = f"{self._config.cluster_ref}/kubernetes/"
        applicable = tuple(
            resource_id
            for resource_id in requested
            if resource_id == self._config.cluster_ref
            or resource_id.startswith(cluster_child_prefix)
        )
        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("Kubernetes event reader clock MUST be timezone-aware")
        exact_uid = None
        if self._config.cluster_ref not in applicable:
            exact_uid = _exact_child_uid(
                applicable,
                resource_identity=resource_identity,
                cluster_ref=self._config.cluster_ref,
            )
        if self._config.cluster_ref not in applicable and exact_uid is None:
            return self._result(
                requested,
                observed_at=observed_at,
                events=(),
                complete=False,
                limitation="source_scope_incomplete",
            )
        try:
            headers = await self._auth.headers()
            request_headers = dict(headers)
            request_headers["Accept-Encoding"] = "identity"
            params = {"limit": str(_MAX_EVENTS + 1)}
            if exact_uid is not None:
                params["fieldSelector"] = f"involvedObject.uid={exact_uid}"
            async with self._client() as client:
                async with client.stream(
                    "GET",
                    f"{self._config.api_server.rstrip('/')}/api/v1/events",
                    params=params,
                    headers=request_headers,
                    timeout=self._config.timeout_seconds,
                ) as response:
                    response.raise_for_status()
                    content_encoding = response.headers.get("content-encoding", "identity")
                    if content_encoding.casefold() != "identity":
                        return self._invalid_result(requested, observed_at)
                    content_length = response.headers.get("content-length")
                    if content_length is not None and (
                        not content_length.isdecimal()
                        or int(content_length) > self._config.max_response_bytes
                    ):
                        return self._invalid_result(requested, observed_at)
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > self._config.max_response_bytes:
                            return self._result(
                                requested,
                                observed_at=observed_at,
                                events=(),
                                complete=False,
                                limitation="resource_event_response_invalid",
                            )
                        body.extend(chunk)
        except (
            KubernetesResourceEventHistoryError,
            httpx.HTTPError,
            OSError,
            ssl.SSLError,
        ):
            return self._result(
                requested,
                observed_at=observed_at,
                events=(),
                complete=False,
                limitation="source_unavailable",
            )
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            payload = None
        if not isinstance(payload, Mapping):
            return self._invalid_result(requested, observed_at)
        items = payload.get("items")
        metadata = payload.get("metadata")
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            return self._invalid_result(requested, observed_at)
        if not isinstance(metadata, Mapping):
            return self._invalid_result(requested, observed_at)
        continuation = metadata.get("continue")
        if continuation is not None and not isinstance(continuation, str):
            return self._invalid_result(requested, observed_at)

        cutoff = observed_at - timedelta(seconds=lookback_seconds)
        malformed = False
        events: list[ResourceEventObservation] = []
        for item in items[:_MAX_EVENTS]:
            if not isinstance(item, Mapping):
                malformed = True
                continue
            parsed = _event(
                item,
                requested=frozenset(applicable),
                cluster_ref=self._config.cluster_ref,
            )
            malformed = malformed or parsed.malformed
            event = parsed.event
            if event is None:
                continue
            if event.occurred_at > observed_at:
                malformed = True
                continue
            if event.occurred_at >= cutoff:
                events.append(event)
        events.sort(key=lambda item: (item.occurred_at, item.evidence_ref))
        truncated = len(items) > _MAX_EVENTS or bool(continuation)
        limitation = (
            "resource_event_response_invalid"
            if malformed
            else "result_limit"
            if truncated
            else "source_scope_incomplete"
            if len(applicable) != len(requested)
            else "source_retention_unverified"
        )
        return self._result(
            requested,
            observed_at=observed_at,
            events=tuple(events),
            complete=limitation is None,
            limitation=limitation,
        )

    def _client(self) -> httpx.AsyncClient:
        if self._client_factory is not None:
            return self._client_factory()
        if self._config.ca_path is None and self._config.ca_pem is None:
            raise KubernetesResourceEventHistoryError("Kubernetes event CA bundle is unavailable")
        context = ssl.create_default_context(
            cafile=str(self._config.ca_path) if self._config.ca_path is not None else None,
            cadata=self._config.ca_pem,
        )
        return httpx.AsyncClient(verify=context)

    def _invalid_result(
        self,
        resource_ids: tuple[str, ...],
        observed_at: datetime,
    ) -> ResourceEventCollection:
        return self._result(
            resource_ids,
            observed_at=observed_at,
            events=(),
            complete=False,
            limitation="resource_event_response_invalid",
        )

    def _result(
        self,
        resource_ids: tuple[str, ...],
        *,
        observed_at: datetime,
        events: tuple[ResourceEventObservation, ...],
        complete: bool,
        limitation: str | None,
    ) -> ResourceEventCollection:
        material = "|".join(
            (
                *resource_ids,
                *(event.evidence_ref for event in events),
                observed_at.isoformat(),
                "complete" if complete else limitation or "incomplete",
            )
        )
        return ResourceEventCollection(
            resource_ids=resource_ids,
            events=events,
            observed_at=observed_at,
            complete=complete,
            limitation=limitation,
            attempt_ref=(
                f"kubernetes-resource-event:{hashlib.sha256(material.encode()).hexdigest()}"
            ),
        )


def _event(
    item: Mapping[str, Any],
    *,
    requested: frozenset[str],
    cluster_ref: str,
) -> _ParsedEvent:
    metadata = item.get("metadata")
    involved = item.get("involvedObject")
    if not isinstance(metadata, Mapping) or not isinstance(involved, Mapping):
        return _ParsedEvent(event=None, malformed=True)
    event_uid = _text(metadata.get("uid"), maximum=512)
    object_uid = _text(involved.get("uid"), maximum=512)
    kind = _text(involved.get("kind"), maximum=64)
    reason = _text(item.get("reason"), maximum=128)
    status = _text(item.get("type"), maximum=128)
    occurred_at = _event_time(item, metadata=metadata)
    if (
        event_uid is None
        or object_uid is None
        or kind is None
        or reason is None
        or status is None
        or occurred_at is None
    ):
        return _ParsedEvent(event=None, malformed=True)
    mapping = _KIND_TO_RESOURCE_TYPE.get(kind)
    direct_id = None
    if mapping is not None:
        resource_type, namespaced = mapping
        namespace = _text(involved.get("namespace"), maximum=253) if namespaced else None
        if namespaced and namespace is None:
            return _ParsedEvent(event=None, malformed=True)
        direct_id = kubernetes_resource_id(
            cluster_ref=cluster_ref,
            resource_type=resource_type,
            uid=object_uid,
            namespace=namespace,
        )
    resource_id = (
        direct_id
        if direct_id is not None and direct_id in requested
        else cluster_ref
        if cluster_ref in requested
        else None
    )
    if resource_id is None:
        return _ParsedEvent(event=None)
    event_kind = _event_kind(reason, message=item.get("message"))
    normalized_status = _machine_token(status, fallback="unknown")
    classification = f"kubernetes_{_machine_token(kind, fallback='object')}"[:64]
    evidence_material = "|".join(
        (
            event_uid,
            object_uid,
            resource_id,
            event_kind,
            normalized_status,
            occurred_at.isoformat(),
        )
    )
    return _ParsedEvent(
        event=ResourceEventObservation(
            resource_id=resource_id,
            event_family=KUBERNETES_EVENT_FAMILY,
            event_kind=event_kind,
            status=normalized_status,
            classification=classification,
            occurred_at=occurred_at,
            evidence_ref=(
                "kubernetes-resource-event:"
                f"{hashlib.sha256(evidence_material.encode()).hexdigest()}"
            ),
        ),
    )


def _exact_child_uid(
    applicable: tuple[str, ...],
    *,
    resource_identity: Mapping[str, Mapping[str, str]] | None,
    cluster_ref: str,
) -> str | None:
    if len(applicable) != 1 or resource_identity is None:
        return None
    resource_id = applicable[0]
    identity = resource_identity.get(resource_id)
    if not isinstance(identity, Mapping):
        return None
    uid = identity.get("uid")
    observed_cluster = identity.get("cluster_ref")
    if (
        not isinstance(uid, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{1,512}", uid) is None
        or observed_cluster != cluster_ref
    ):
        return None
    prefix = f"{cluster_ref}/kubernetes/"
    if not resource_id.startswith(prefix):
        return None
    identity_parts = resource_id.removeprefix(prefix).split("/")
    if len(identity_parts) != 3:
        return None
    resource_type, namespace_key, _digest = identity_parts
    namespace = None if namespace_key == "_cluster" else namespace_key
    expected = kubernetes_resource_id(
        cluster_ref=cluster_ref,
        resource_type=resource_type,
        uid=uid,
        namespace=namespace,
    )
    return uid if expected == resource_id else None


def _event_time(item: Mapping[str, Any], *, metadata: Mapping[str, Any]) -> datetime | None:
    series = item.get("series")
    candidates = (
        series.get("lastObservedTime") if isinstance(series, Mapping) else None,
        item.get("lastTimestamp"),
        item.get("eventTime"),
        item.get("firstTimestamp"),
        metadata.get("creationTimestamp"),
    )
    return next((parsed for value in candidates if (parsed := _timestamp(value)) is not None), None)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _text(value: object, *, maximum: int) -> str | None:
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= maximum else None


def _machine_token(value: object, *, fallback: str) -> str:
    normalized = "_".join(str(value or "").casefold().replace("-", " ").split())
    return normalized[:128] or fallback


def _event_kind(reason: str, *, message: object) -> str:
    if reason.casefold() == "failed" and isinstance(message, str):
        exact_error = message.strip().casefold()
        if exact_error == "error: imagepullbackoff":
            return "imagepullbackoff"
        if exact_error == "error: errimagepull":
            return "errimagepull"
    return _machine_token(reason, fallback="unknown")


__all__ = [
    "KubernetesResourceEventHistoryConfig",
    "KubernetesResourceEventHistoryError",
    "KubernetesResourceEventHistoryReader",
]
