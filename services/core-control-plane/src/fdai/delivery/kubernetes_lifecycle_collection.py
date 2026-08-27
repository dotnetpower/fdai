"""Bounded Kubernetes Event watch collection for durable lifecycle evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleBatch,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
    lifecycle_digest,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiAuth

_MAX_ITEMS: Final = 256
_MAX_RESPONSE_BYTES: Final = 524_288
_MAX_LINE_BYTES: Final = 65_536
_WATCH_SECONDS: Final = 20
_LIFECYCLE_KIND = {
    "backoff": "backoff",
    "failed": "failed",
    "killing": "terminating",
    "scheduled": "scheduled",
    "started": "started",
    "successfulcreate": "created",
    "successfuldelete": "deleted",
    "unhealthy": "unhealthy",
}


class KubernetesLifecycleCollectionError(RuntimeError):
    """One bounded lifecycle collection could not complete safely."""


class KubernetesLifecycleCollector:
    """Seed an opaque cursor once, then collect one bounded watch window."""

    def __init__(
        self,
        *,
        api_server: str,
        cluster_ref: str,
        auth: KubernetesApiAuth,
        http_client: httpx.AsyncClient,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_server = api_server.rstrip("/")
        self._cluster_ref = cluster_ref
        self._auth = auth
        self._http = http_client
        self._now = now or (lambda: datetime.now(UTC))

    async def collect(
        self,
        cursor: KubernetesLifecycleCursor,
    ) -> KubernetesLifecycleBatch:
        """Return a seed checkpoint or one bounded watch batch."""

        if cursor.cluster_ref != self._cluster_ref:
            raise ValueError("Kubernetes lifecycle cursor changed cluster scope")
        observed_at = self._now()
        headers = dict(await self._auth.headers())
        headers["Accept-Encoding"] = "identity"
        if cursor.resume_token is None:
            return await self._seed(cursor, headers=headers, observed_at=observed_at)
        return await self._watch(cursor, headers=headers, observed_at=observed_at)

    async def _seed(
        self,
        cursor: KubernetesLifecycleCursor,
        *,
        headers: Mapping[str, str],
        observed_at: datetime,
    ) -> KubernetesLifecycleBatch:
        try:
            response = await self._http.get(
                f"{self._api_server}/api/v1/events",
                params={"limit": "1"},
                headers=dict(headers),
                timeout=10,
            )
        except httpx.HTTPError:
            return self._limited(cursor, observed_at, "source_unavailable")
        limitation = _http_limitation(response)
        if limitation is not None:
            return self._limited(
                cursor,
                observed_at,
                limitation,
                reset=limitation == "cursor_expired",
            )
        payload = _bounded_json(response)
        metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
        token = metadata.get("resourceVersion") if isinstance(metadata, Mapping) else None
        if not isinstance(token, str) or not token:
            return self._limited(cursor, observed_at, "resource_event_response_invalid")
        return KubernetesLifecycleBatch(
            cluster_ref=self._cluster_ref,
            expected_sequence=cursor.sequence,
            next_resume_token=token,
            coverage_started_at=observed_at,
            coverage_through_at=observed_at,
            observations=(),
            limitation=None,
        )

    async def _watch(
        self,
        cursor: KubernetesLifecycleCursor,
        *,
        headers: Mapping[str, str],
        observed_at: datetime,
    ) -> KubernetesLifecycleBatch:
        try:
            response = await self._http.get(
                f"{self._api_server}/api/v1/events",
                params={
                    "allowWatchBookmarks": "true",
                    "resourceVersion": cursor.resume_token or "",
                    "timeoutSeconds": str(_WATCH_SECONDS),
                    "watch": "true",
                },
                headers=dict(headers),
                timeout=_WATCH_SECONDS + 5,
            )
        except httpx.HTTPError:
            return self._limited(cursor, observed_at, "source_unavailable")
        limitation = _http_limitation(response)
        if limitation is not None:
            return self._limited(
                cursor,
                observed_at,
                limitation,
                reset=limitation == "cursor_expired",
            )
        content_limited = len(response.content) > _MAX_RESPONSE_BYTES
        content = response.content[:_MAX_RESPONSE_BYTES]
        if content_limited:
            content = content.rsplit(b"\n", 1)[0]
        token = cursor.resume_token
        observations: dict[str, KubernetesLifecycleObservation] = {}
        for raw_line in content.splitlines():
            if len(raw_line) > _MAX_LINE_BYTES:
                return self._limited(cursor, observed_at, "resource_event_response_invalid")
            try:
                envelope = json.loads(raw_line)
            except (UnicodeDecodeError, ValueError):
                return self._limited(cursor, observed_at, "resource_event_response_invalid")
            if not isinstance(envelope, Mapping):
                return self._limited(cursor, observed_at, "resource_event_response_invalid")
            action = envelope.get("type")
            item = envelope.get("object")
            if action == "ERROR":
                code = item.get("code") if isinstance(item, Mapping) else None
                return self._limited(
                    cursor,
                    observed_at,
                    "cursor_expired" if code == 410 else "source_unavailable",
                    reset=code == 410,
                )
            if not isinstance(action, str) or not isinstance(item, Mapping):
                return self._limited(cursor, observed_at, "resource_event_response_invalid")
            metadata = item.get("metadata")
            current = metadata.get("resourceVersion") if isinstance(metadata, Mapping) else None
            if action == "BOOKMARK":
                if isinstance(current, str) and current:
                    token = current
                continue
            observation = _observation(
                item,
                action=action,
                cluster_ref=self._cluster_ref,
                recorded_at=observed_at,
            )
            if observation is not None:
                if len(observations) == _MAX_ITEMS:
                    return KubernetesLifecycleBatch(
                        cluster_ref=self._cluster_ref,
                        expected_sequence=cursor.sequence,
                        next_resume_token=token,
                        coverage_started_at=cursor.coverage_started_at,
                        coverage_through_at=observed_at,
                        observations=tuple(observations[key] for key in sorted(observations)),
                        limitation="result_limit",
                    )
                observations[observation.observation_id] = observation
            if isinstance(current, str) and current:
                token = current
        return KubernetesLifecycleBatch(
            cluster_ref=self._cluster_ref,
            expected_sequence=cursor.sequence,
            next_resume_token=token,
            coverage_started_at=cursor.coverage_started_at,
            coverage_through_at=observed_at,
            observations=tuple(observations[key] for key in sorted(observations)),
            limitation="result_limit" if content_limited else None,
        )

    def _limited(
        self,
        cursor: KubernetesLifecycleCursor,
        observed_at: datetime,
        limitation: str,
        *,
        reset: bool = False,
    ) -> KubernetesLifecycleBatch:
        return KubernetesLifecycleBatch(
            cluster_ref=self._cluster_ref,
            expected_sequence=cursor.sequence,
            next_resume_token=None if reset else cursor.resume_token,
            coverage_started_at=observed_at if reset else cursor.coverage_started_at,
            coverage_through_at=max(cursor.coverage_through_at, observed_at),
            observations=(),
            limitation=limitation,
        )


def _http_limitation(response: httpx.Response) -> str | None:
    if response.status_code == 410:
        return "cursor_expired"
    if response.status_code in {401, 403}:
        return "authorization_denied"
    if response.status_code != 200:
        return "source_unavailable"
    if response.headers.get("content-encoding", "identity").casefold() != "identity":
        return "resource_event_response_invalid"
    return None


def _bounded_json(response: httpx.Response) -> Mapping[str, Any] | None:
    if len(response.content) > _MAX_RESPONSE_BYTES:
        return None
    try:
        value = response.json()
    except ValueError:
        return None
    return value if isinstance(value, Mapping) else None


def _observation(
    item: Mapping[str, Any],
    *,
    action: str,
    cluster_ref: str,
    recorded_at: datetime,
) -> KubernetesLifecycleObservation | None:
    metadata = item.get("metadata")
    involved = item.get("involvedObject")
    if not isinstance(metadata, Mapping) or not isinstance(involved, Mapping):
        return None
    event_uid = _text(metadata.get("uid"))
    source_revision = _text(metadata.get("resourceVersion"))
    object_uid = _text(involved.get("uid"))
    object_kind = _text(involved.get("kind"))
    reason = _text(item.get("reason"))
    event_type = _text(item.get("type"))
    occurred_at = _event_time(item, metadata)
    if (
        event_uid is None
        or source_revision is None
        or object_uid is None
        or object_kind is None
        or reason is None
        or event_type is None
        or occurred_at is None
    ):
        return None
    count = _occurrence_count(item)
    observation_id = lifecycle_digest(
        cluster_ref,
        str(event_uid),
        str(source_revision),
        str(count),
        occurred_at.isoformat(),
    )
    return KubernetesLifecycleObservation(
        observation_id=observation_id,
        cluster_ref=cluster_ref,
        event_uid=event_uid,
        object_uid=object_uid,
        object_kind=object_kind,
        namespace=_text(involved.get("namespace")),
        owner_uid=_owner_uid(involved),
        reason=reason,
        event_type=event_type,
        lifecycle_kind=_LIFECYCLE_KIND.get(reason.casefold(), "other"),
        action=action.casefold(),
        occurred_at=occurred_at,
        recorded_at=max(recorded_at, occurred_at),
        source_revision=source_revision,
        occurrence_count=count,
        evidence_ref=f"kubernetes-lifecycle:{observation_id.removeprefix('sha256:')}",
    )


def _owner_uid(involved: Mapping[str, Any]) -> str | None:
    owners = involved.get("ownerReferences")
    if not isinstance(owners, Sequence) or isinstance(owners, (str, bytes)):
        return None
    return next(
        (
            uid
            for item in owners
            if isinstance(item, Mapping) and (uid := _text(item.get("uid"))) is not None
        ),
        None,
    )


def _event_time(item: Mapping[str, Any], metadata: Mapping[str, Any]) -> datetime | None:
    series = item.get("series")
    values = (
        series.get("lastObservedTime") if isinstance(series, Mapping) else None,
        item.get("eventTime"),
        item.get("lastTimestamp"),
        item.get("firstTimestamp"),
        metadata.get("creationTimestamp"),
    )
    for value in values:
        parsed = _timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _occurrence_count(item: Mapping[str, Any]) -> int:
    series = item.get("series")
    value = series.get("count") if isinstance(series, Mapping) else item.get("count")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["KubernetesLifecycleCollectionError", "KubernetesLifecycleCollector"]
