"""Bounded resumable Kubernetes lifecycle Event source (list-then-watch)."""

from __future__ import annotations

import hashlib
import json
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlparse

import httpx

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesLifecycleObservation,
    normalize_kubernetes_lifecycle_reason,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiAuth

_MAX_EVENTS: Final = 256
_MAX_RESPONSE_BYTES: Final = 262_144
_MAX_WATCH_LINE_BYTES: Final = 65_536
# A LIST snapshot MUST NOT advance the durable cursor past pages it never fetched.
# Rather than persist a provider-controlled, unbounded-length `continue` token as
# the durable cursor, one `poll()` bounded-drains up to this many pages internally;
# if the list still has not fully drained by then, the whole attempt reports an
# explicit `result_limit` gap and leaves the cursor untouched so the next attempt
# safely restarts the list (idempotent: observations are content-addressed).
_MAX_LIST_PAGES: Final = 8
_MAX_LIST_DRAIN_EVENTS: Final = _MAX_EVENTS * _MAX_LIST_PAGES


class KubernetesLifecycleSourceError(RuntimeError):
    """Report a bounded Kubernetes lifecycle read failure without provider content."""


class _KubernetesLifecycleAuthorizationError(Exception):
    """Signal a 401/403 provider response distinctly from a generic outage."""


@dataclass(frozen=True, slots=True)
class KubernetesLifecycleSourceConfig:
    """Bind one credential-free API endpoint to an exact cluster identity."""

    api_server: str
    cluster_ref: str
    ca_path: Path | None = None
    ca_pem: str | None = None
    list_limit: int = _MAX_EVENTS
    watch_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
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
            raise ValueError("Kubernetes lifecycle api_server MUST be credential-free HTTPS")
        if not self.cluster_ref.strip() or len(self.cluster_ref) > 512:
            raise ValueError("Kubernetes lifecycle cluster_ref MUST be bounded non-empty text")
        if not 1 <= self.list_limit <= _MAX_EVENTS:
            raise ValueError(f"Kubernetes lifecycle list_limit MUST be in [1, {_MAX_EVENTS}]")
        if not 1.0 <= self.watch_timeout_seconds <= 120.0:
            raise ValueError("Kubernetes lifecycle watch_timeout_seconds MUST be in [1, 120]")
        if not 0.1 <= self.connect_timeout_seconds <= 30.0:
            raise ValueError("Kubernetes lifecycle connect_timeout_seconds MUST be in [0.1, 30]")
        if not 1_024 <= self.max_response_bytes <= _MAX_RESPONSE_BYTES:
            raise ValueError(
                f"Kubernetes lifecycle max_response_bytes MUST be in [1024, {_MAX_RESPONSE_BYTES}]"
            )
        if self.ca_path is not None and self.ca_pem is not None:
            raise ValueError("Kubernetes lifecycle source accepts exactly one CA binding")


@dataclass(frozen=True, slots=True)
class KubernetesLifecyclePoll:
    """One bounded provider read, complete or with an explicit coverage gap."""

    cluster_ref: str
    observations: tuple[KubernetesLifecycleObservation, ...]
    next_cursor: str | None
    complete: bool
    limitation: str | None
    attempt_ref: str

    def __post_init__(self) -> None:
        if not self.cluster_ref.strip() or len(self.cluster_ref) > 512:
            raise ValueError("Kubernetes lifecycle poll cluster_ref MUST be bounded non-empty")
        if len(self.observations) > _MAX_LIST_DRAIN_EVENTS:
            raise ValueError("Kubernetes lifecycle poll exceeds its event bound")
        if any(item.cluster_ref != self.cluster_ref for item in self.observations):
            raise ValueError("Kubernetes lifecycle poll widened the requested cluster scope")
        if self.complete == (self.limitation is not None):
            raise ValueError("Kubernetes lifecycle poll completeness and limitation disagree")
        if self.complete and self.next_cursor is None:
            raise ValueError("Kubernetes lifecycle poll MUST carry a cursor when complete")
        if not self.attempt_ref.strip() or len(self.attempt_ref) > 256:
            raise ValueError("Kubernetes lifecycle poll attempt_ref MUST be bounded non-empty")


class KubernetesLifecycleSource(Protocol):
    """Read one bounded, resumable slice of cluster lifecycle Events."""

    async def poll(
        self,
        *,
        cluster_ref: str,
        cursor: str | None,
    ) -> KubernetesLifecyclePoll: ...


class KubernetesLifecycleWatchSource:
    """List-then-watch Kubernetes Event source bounded by size, count, and time."""

    def __init__(
        self,
        *,
        auth: KubernetesApiAuth,
        config: KubernetesLifecycleSourceConfig,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._auth: Final = auth
        self._config: Final = config
        self._client_factory: Final = client_factory
        self._now: Final = now or (lambda: datetime.now(UTC))

    async def poll(
        self,
        *,
        cluster_ref: str,
        cursor: str | None,
    ) -> KubernetesLifecyclePoll:
        """Return the next bounded slice, resuming from `cursor` when present."""

        if cluster_ref != self._config.cluster_ref:
            raise ValueError("Kubernetes lifecycle source received a foreign cluster_ref")
        recorded_time = self._now()
        if recorded_time.tzinfo is None:
            raise ValueError("Kubernetes lifecycle source clock MUST be timezone-aware")
        try:
            headers = await self._auth.headers()
        except Exception:  # noqa: BLE001 - auth failures never leak provider content
            # Preserve the caller's cursor: a transient auth blip MUST NOT discard an
            # already-durable checkpoint, only `cursor_expired` resets it.
            return self._gap(cluster_ref, limitation="authorization_failed", next_cursor=cursor)
        request_headers = dict(headers)
        request_headers["Accept-Encoding"] = "identity"
        if cursor is None:
            return await self._list(
                cluster_ref, headers=request_headers, recorded_time=recorded_time
            )
        return await self._watch(
            cluster_ref,
            cursor=cursor,
            headers=request_headers,
            recorded_time=recorded_time,
        )

    async def _list(
        self,
        cluster_ref: str,
        *,
        headers: dict[str, str],
        recorded_time: datetime,
    ) -> KubernetesLifecyclePoll:
        """Bounded-drain up to `_MAX_LIST_PAGES` continuation pages of one snapshot.

        The durable cursor only ever advances to the snapshot `resourceVersion` once
        every page has been fetched (no `continue` token remains); an incomplete
        drain reports an explicit `result_limit` gap and leaves the cursor untouched
        so the next attempt safely restarts the whole list rather than silently
        skipping the pages it never reached.
        """

        observations: list[KubernetesLifecycleObservation] = []
        malformed = False
        continue_token: str | None = None
        for _ in range(_MAX_LIST_PAGES):
            params = {"limit": str(self._config.list_limit + 1)}
            if continue_token is not None:
                params["continue"] = continue_token
            try:
                body = await self._get(params=params, headers=headers)
            except _KubernetesLifecycleAuthorizationError:
                return self._gap(cluster_ref, limitation="authorization_failed")
            if body is None:
                return self._gap(cluster_ref, limitation="source_unavailable")
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, ValueError):
                return self._gap(cluster_ref, limitation="lifecycle_response_invalid")
            if not isinstance(payload, Mapping):
                return self._gap(cluster_ref, limitation="lifecycle_response_invalid")
            items = payload.get("items")
            metadata = payload.get("metadata")
            if (
                not isinstance(items, Sequence)
                or isinstance(items, (str, bytes))
                or not isinstance(metadata, Mapping)
            ):
                return self._gap(cluster_ref, limitation="lifecycle_response_invalid")
            resource_version = _text(metadata.get("resourceVersion"), maximum=128)
            if resource_version is None:
                return self._gap(cluster_ref, limitation="lifecycle_response_invalid")
            continuation = metadata.get("continue")
            if continuation is not None and not isinstance(continuation, str):
                return self._gap(cluster_ref, limitation="lifecycle_response_invalid")
            if len(items) > self._config.list_limit and not continuation:
                malformed = True
            for item in items[: self._config.list_limit]:
                if not isinstance(item, Mapping):
                    malformed = True
                    continue
                observation = _observation(
                    item, cluster_ref=cluster_ref, recorded_time=recorded_time
                )
                if observation is None:
                    malformed = True
                    continue
                observations.append(observation)
            if not continuation:
                observations.sort(key=lambda item: (item.event_time, item.evidence_ref))
                limitation = "lifecycle_response_invalid" if malformed else None
                return self._result(
                    cluster_ref,
                    observations=tuple(observations),
                    next_cursor=resource_version,
                    limitation=limitation,
                )
            continue_token = continuation
        observations.sort(key=lambda item: (item.event_time, item.evidence_ref))
        return self._result(
            cluster_ref,
            observations=tuple(observations),
            next_cursor=None,
            limitation="result_limit",
        )

    async def _watch(
        self,
        cluster_ref: str,
        *,
        cursor: str,
        headers: dict[str, str],
        recorded_time: datetime,
    ) -> KubernetesLifecyclePoll:
        try:
            watch_result = await self._get_watch_lines(cursor=cursor, headers=headers)
        except _KubernetesLifecycleAuthorizationError:
            # Preserve the caller's cursor: a transient auth blip MUST NOT discard an
            # already-durable checkpoint, only `cursor_expired` resets it.
            return self._gap(cluster_ref, limitation="authorization_failed", next_cursor=cursor)
        if watch_result is None:
            # Preserve the durable cursor on a transient outage: only an explicit
            # `cursor_expired` gap (HTTP 410 Gone) resets it to `None`.
            return self._gap(cluster_ref, limitation="source_unavailable", next_cursor=cursor)
        lines, truncated = watch_result
        observations: list[KubernetesLifecycleObservation] = []
        next_cursor = cursor
        malformed = False
        gone = False
        for line in lines:
            if not line.strip():
                continue
            try:
                envelope = json.loads(line)
            except (UnicodeDecodeError, ValueError):
                malformed = True
                continue
            if not isinstance(envelope, Mapping):
                malformed = True
                continue
            event_type = envelope.get("type")
            raw_object = envelope.get("object")
            if not isinstance(event_type, str) or not isinstance(raw_object, Mapping):
                malformed = True
                continue
            if event_type == "ERROR":
                status_code = raw_object.get("code")
                if status_code == 410:
                    gone = True
                    break
                malformed = True
                continue
            if event_type == "BOOKMARK":
                bookmark_version = _text(
                    (raw_object.get("metadata") or {}).get("resourceVersion")
                    if isinstance(raw_object.get("metadata"), Mapping)
                    else None,
                    maximum=128,
                )
                if bookmark_version is not None:
                    next_cursor = bookmark_version
                continue
            if event_type == "DELETED":
                # Event objects being reaped server-side carries no lifecycle meaning;
                # only ADDED/MODIFIED payloads describe a new observed reason.
                revision = _text(
                    (raw_object.get("metadata") or {}).get("resourceVersion")
                    if isinstance(raw_object.get("metadata"), Mapping)
                    else None,
                    maximum=128,
                )
                if revision is not None:
                    next_cursor = revision
                continue
            if event_type not in {"ADDED", "MODIFIED"}:
                malformed = True
                continue
            observation = _observation(
                raw_object, cluster_ref=cluster_ref, recorded_time=recorded_time
            )
            if observation is None:
                malformed = True
                continue
            observations.append(observation)
            next_cursor = observation.source_revision
        if gone:
            return self._gap(cluster_ref, limitation="cursor_expired", next_cursor=None)
        observations.sort(key=lambda item: (item.event_time, item.evidence_ref))
        # A discarded envelope (byte/line/UTF-8 bound) MUST NOT silently report success:
        # `next_cursor` here only ever reflects the lines actually decoded before the
        # bound was hit, so advancing to it never skips past unseen content, but the
        # gap itself MUST still be surfaced rather than reported as `complete`.
        limitation = (
            "lifecycle_response_invalid" if malformed else "result_limit" if truncated else None
        )
        return self._result(
            cluster_ref,
            observations=tuple(observations),
            next_cursor=next_cursor,
            limitation=limitation,
        )

    async def _get(
        self,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> bytes | None:
        try:
            async with self._client() as client:
                async with client.stream(
                    "GET",
                    f"{self._config.api_server.rstrip('/')}/api/v1/events",
                    params=params,
                    headers=headers,
                    timeout=self._config.connect_timeout_seconds,
                ) as response:
                    if response.status_code in (401, 403):
                        raise _KubernetesLifecycleAuthorizationError(str(response.status_code))
                    response.raise_for_status()
                    content_encoding = response.headers.get("content-encoding", "identity")
                    if content_encoding.casefold() != "identity":
                        return None
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > self._config.max_response_bytes:
                            return None
                        body.extend(chunk)
                    return bytes(body)
        except (KubernetesLifecycleSourceError, httpx.HTTPError, OSError, ssl.SSLError):
            return None

    async def _get_watch_lines(
        self,
        *,
        cursor: str,
        headers: Mapping[str, str],
    ) -> tuple[list[str], bool] | None:
        """Return decoded watch lines plus whether a bound cut the stream short.

        `truncated=True` means a byte, line-length, or UTF-8 bound was hit before
        the stream's natural end; the returned `lines` never include the discarded
        envelope itself or anything after it, so a caller advancing its cursor from
        `lines` alone can never skip past content it never actually received.
        """

        params = {
            "watch": "true",
            "resourceVersion": cursor,
            "timeoutSeconds": str(int(self._config.watch_timeout_seconds)),
            "allowWatchBookmarks": "true",
            "limit": str(self._config.list_limit),
        }
        try:
            async with self._client() as client:
                async with client.stream(
                    "GET",
                    f"{self._config.api_server.rstrip('/')}/api/v1/events",
                    params=params,
                    headers=headers,
                    timeout=(
                        self._config.watch_timeout_seconds + self._config.connect_timeout_seconds
                    ),
                ) as response:
                    if response.status_code == 410:
                        return [json.dumps({"type": "ERROR", "object": {"code": 410}})], False
                    if response.status_code in (401, 403):
                        raise _KubernetesLifecycleAuthorizationError(str(response.status_code))
                    response.raise_for_status()
                    content_encoding = response.headers.get("content-encoding", "identity")
                    if content_encoding.casefold() != "identity":
                        return None
                    lines: list[str] = []
                    buffer = bytearray()
                    total = 0
                    async for chunk in response.aiter_raw():
                        total += len(chunk)
                        if total > self._config.max_response_bytes:
                            return lines, True
                        buffer.extend(chunk)
                        while b"\n" in buffer:
                            raw_line, _, remainder = buffer.partition(b"\n")
                            buffer = bytearray(remainder)
                            if len(raw_line) > _MAX_WATCH_LINE_BYTES:
                                return lines, True
                            try:
                                decoded_line = raw_line.decode("utf-8")
                            except UnicodeDecodeError:
                                return lines, True
                            lines.append(decoded_line)
                            if len(lines) >= _MAX_EVENTS:
                                return lines, True
                    if buffer:
                        if len(buffer) > _MAX_WATCH_LINE_BYTES:
                            return lines, True
                        try:
                            lines.append(bytes(buffer).decode("utf-8"))
                        except UnicodeDecodeError:
                            return lines, True
                    return lines, False
        except (KubernetesLifecycleSourceError, httpx.HTTPError, OSError, ssl.SSLError):
            return None

    def _client(self) -> httpx.AsyncClient:
        if self._client_factory is not None:
            return self._client_factory()
        if self._config.ca_path is None and self._config.ca_pem is None:
            raise KubernetesLifecycleSourceError("Kubernetes lifecycle CA bundle is unavailable")
        context = ssl.create_default_context(
            cafile=str(self._config.ca_path) if self._config.ca_path is not None else None,
            cadata=self._config.ca_pem,
        )
        return httpx.AsyncClient(verify=context)

    def _gap(
        self,
        cluster_ref: str,
        *,
        limitation: str,
        next_cursor: str | None = None,
    ) -> KubernetesLifecyclePoll:
        return self._result(
            cluster_ref,
            observations=(),
            next_cursor=next_cursor,
            limitation=limitation,
        )

    def _result(
        self,
        cluster_ref: str,
        *,
        observations: tuple[KubernetesLifecycleObservation, ...],
        next_cursor: str | None,
        limitation: str | None,
    ) -> KubernetesLifecyclePoll:
        material = "|".join(
            (
                cluster_ref,
                *(item.evidence_ref for item in observations),
                next_cursor or "none",
                limitation or "complete",
            )
        )
        return KubernetesLifecyclePoll(
            cluster_ref=cluster_ref,
            observations=observations,
            next_cursor=next_cursor,
            complete=limitation is None,
            limitation=limitation,
            attempt_ref=f"kubernetes-lifecycle:{hashlib.sha256(material.encode()).hexdigest()}",
        )


def _observation(
    item: Mapping[str, Any],
    *,
    cluster_ref: str,
    recorded_time: datetime,
) -> KubernetesLifecycleObservation | None:
    metadata = item.get("metadata")
    involved = item.get("involvedObject")
    if not isinstance(metadata, Mapping) or not isinstance(involved, Mapping):
        return None
    event_uid = _text(metadata.get("uid"), maximum=512)
    object_uid = _text(involved.get("uid"), maximum=512)
    reason = _text(item.get("reason"), maximum=128)
    event_type = _text(item.get("type"), maximum=64)
    source_revision = _text(metadata.get("resourceVersion"), maximum=128)
    event_time = _event_time(item, metadata=metadata)
    if (
        event_uid is None
        or object_uid is None
        or reason is None
        or event_type is None
        or source_revision is None
        or event_time is None
    ):
        return None
    namespace = _text(involved.get("namespace"), maximum=253)
    owner_uid = _owner_uid(item)
    category = normalize_kubernetes_lifecycle_reason(reason)
    evidence_material = "|".join(
        (
            cluster_ref,
            event_uid,
            object_uid,
            reason,
            source_revision,
            event_time.isoformat(),
        )
    )
    return KubernetesLifecycleObservation(
        cluster_ref=cluster_ref,
        namespace=namespace,
        object_uid=object_uid,
        owner_uid=owner_uid,
        reason=reason,
        category=category,
        event_type=event_type,
        event_time=event_time,
        recorded_time=recorded_time,
        source_revision=source_revision,
        evidence_ref=f"kubernetes-lifecycle:{hashlib.sha256(evidence_material.encode()).hexdigest()}",
    )


def _owner_uid(item: Mapping[str, Any]) -> str | None:
    related = item.get("related")
    if not isinstance(related, Mapping):
        return None
    return _text(related.get("uid"), maximum=512)


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


__all__ = [
    "KubernetesLifecyclePoll",
    "KubernetesLifecycleSource",
    "KubernetesLifecycleSourceConfig",
    "KubernetesLifecycleSourceError",
    "KubernetesLifecycleWatchSource",
]
