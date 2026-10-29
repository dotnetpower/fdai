"""Outbound Kubernetes lifecycle Event history through the connector gateway.

The gateway owns the single durable writer per cluster: it acquires the store's lease, checks the
observer's expected sequence, and appends one batch atomically. The observer holds no database
access and no cursor of its own; each cycle asks the gateway for the durable cursor, collects one
bounded watch window from it, and sends the batch back. A lost response is safe to retry because
the sequence check and idempotent observation identities reject a duplicate.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import httpx
from fdai_service_contracts.cluster_connector import ConnectorRegistration

from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleBatch,
    KubernetesLifecycleCoverageSegment,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_connector_snapshot import ConnectorRegistrationReader
from fdai.delivery.kubernetes_connector_transport import ConnectorTransportConfig

CAPABILITY: Literal["lifecycle.events"] = "lifecycle.events"
CURSOR_PATH = "/v1/connector/events/cursor"
BATCH_PATH = "/v1/connector/events"
MAX_BATCH_BYTES = 2_097_152
MAX_OBSERVATIONS = 256
LEASE_SECONDS = 60
_RESPONSE_LIMIT = 8_192
_OBSERVATION_FIELDS = (
    "observation_id event_uid object_uid object_kind namespace owner_uid reason event_type "
    "lifecycle_kind action occurred_at recorded_at source_revision occurrence_count evidence_ref"
).split()
_BATCH_FIELDS = {
    "cluster_ref",
    "expected_sequence",
    "next_resume_token",
    "coverage_started_at",
    "coverage_through_at",
    "observations",
    "limitation",
    "incomplete_coverage_segment",
}
_CURSOR_FIELDS = {
    "cluster_ref",
    "sequence",
    "resume_token",
    "coverage_started_at",
    "coverage_through_at",
    "retention_floor_at",
    "limitation",
}


class LifecycleStore(Protocol):
    async def acquire(
        self, *, cluster_ref: str, holder: str, now: datetime, lease_until: datetime
    ) -> KubernetesLifecycleCursor | None: ...

    async def append(
        self, batch: KubernetesLifecycleBatch, *, holder: str, now: datetime
    ) -> bool: ...


class ConnectorEventError(ValueError):
    """Reject an event transfer without exposing its content."""


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ConnectorEventError("duplicate event transfer field")
        value[key] = item
    return value


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ConnectorEventError("event transfer time is invalid")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ConnectorEventError("event transfer time must be timezone-aware")
    return moment


def encode_cursor(cursor: KubernetesLifecycleCursor) -> bytes:
    return json.dumps(
        {
            "cluster_ref": cursor.cluster_ref,
            "sequence": cursor.sequence,
            "resume_token": cursor.resume_token,
            "coverage_started_at": cursor.coverage_started_at.astimezone(UTC).isoformat(),
            "coverage_through_at": cursor.coverage_through_at.astimezone(UTC).isoformat(),
            "retention_floor_at": cursor.retention_floor_at.astimezone(UTC).isoformat(),
            "limitation": cursor.limitation,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def decode_cursor(content: bytes) -> KubernetesLifecycleCursor:
    try:
        value = json.loads(content, object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != _CURSOR_FIELDS:
            raise ConnectorEventError("event cursor has an invalid shape")
        sequence = value["sequence"]
        if type(sequence) is not int:
            raise ConnectorEventError("event cursor sequence is invalid")
        return KubernetesLifecycleCursor(
            cluster_ref=str(value["cluster_ref"]),
            sequence=sequence,
            resume_token=None if value["resume_token"] is None else str(value["resume_token"]),
            coverage_started_at=_time(value["coverage_started_at"]),
            coverage_through_at=_time(value["coverage_through_at"]),
            retention_floor_at=_time(value["retention_floor_at"]),
            limitation=None if value["limitation"] is None else str(value["limitation"]),
        )
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ConnectorEventError("event cursor is invalid") from exc


def encode_batch(batch: KubernetesLifecycleBatch) -> bytes:
    segment = batch.incomplete_coverage_segment
    body = {
        "cluster_ref": batch.cluster_ref,
        "expected_sequence": batch.expected_sequence,
        "next_resume_token": batch.next_resume_token,
        "coverage_started_at": batch.coverage_started_at.astimezone(UTC).isoformat(),
        "coverage_through_at": batch.coverage_through_at.astimezone(UTC).isoformat(),
        "limitation": batch.limitation,
        "observations": [
            {
                name: (
                    getattr(item, name).astimezone(UTC).isoformat()
                    if isinstance(getattr(item, name), datetime)
                    else getattr(item, name)
                )
                for name in _OBSERVATION_FIELDS
            }
            for item in batch.observations
        ],
        "incomplete_coverage_segment": None
        if segment is None
        else {
            "started_at": segment.started_at.astimezone(UTC).isoformat(),
            "ended_at": segment.ended_at.astimezone(UTC).isoformat(),
            "limitation": segment.limitation,
        },
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_BATCH_BYTES:
        raise ConnectorEventError("event batch exceeds its byte limit")
    return encoded


def decode_batch(content: bytes, *, cluster_ref: str) -> KubernetesLifecycleBatch:
    """Rebuild a batch through the domain validators and bind it to one cluster."""
    if len(content) > MAX_BATCH_BYTES:
        raise ConnectorEventError("event batch exceeds its byte limit")
    try:
        value = json.loads(content, object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != _BATCH_FIELDS:
            raise ConnectorEventError("event batch has an invalid shape")
        if value["cluster_ref"] != cluster_ref:
            raise ConnectorEventError("event batch is not for the enrolled cluster")
        items = value["observations"]
        if not isinstance(items, list) or len(items) > MAX_OBSERVATIONS:
            raise ConnectorEventError("event batch observation count is invalid")
        observations = []
        for item in items:
            if not isinstance(item, dict) or set(item) != set(_OBSERVATION_FIELDS):
                raise ConnectorEventError("event observation has an invalid shape")
            count = item["occurrence_count"]
            if type(count) is not int:
                raise ConnectorEventError("event observation count is invalid")
            observations.append(
                KubernetesLifecycleObservation(
                    cluster_ref=cluster_ref,
                    observation_id=str(item["observation_id"]),
                    event_uid=str(item["event_uid"]),
                    object_uid=str(item["object_uid"]),
                    object_kind=str(item["object_kind"]),
                    namespace=None if item["namespace"] is None else str(item["namespace"]),
                    owner_uid=None if item["owner_uid"] is None else str(item["owner_uid"]),
                    reason=str(item["reason"]),
                    event_type=str(item["event_type"]),
                    lifecycle_kind=str(item["lifecycle_kind"]),
                    action=str(item["action"]),
                    occurred_at=_time(item["occurred_at"]),
                    recorded_at=_time(item["recorded_at"]),
                    source_revision=str(item["source_revision"]),
                    occurrence_count=count,
                    evidence_ref=str(item["evidence_ref"]),
                )
            )
        raw_segment = value["incomplete_coverage_segment"]
        segment = None
        if raw_segment is not None:
            if not isinstance(raw_segment, dict) or set(raw_segment) != {
                "started_at",
                "ended_at",
                "limitation",
            }:
                raise ConnectorEventError("event coverage segment has an invalid shape")
            segment = KubernetesLifecycleCoverageSegment(
                cluster_ref=cluster_ref,
                started_at=_time(raw_segment["started_at"]),
                ended_at=_time(raw_segment["ended_at"]),
                limitation=raw_segment["limitation"],
            )
        sequence = value["expected_sequence"]
        if type(sequence) is not int:
            raise ConnectorEventError("event batch sequence is invalid")
        return KubernetesLifecycleBatch(
            cluster_ref=cluster_ref,
            expected_sequence=sequence,
            next_resume_token=None
            if value["next_resume_token"] is None
            else str(value["next_resume_token"]),
            coverage_started_at=_time(value["coverage_started_at"]),
            coverage_through_at=_time(value["coverage_through_at"]),
            observations=tuple(observations),
            limitation=None if value["limitation"] is None else str(value["limitation"]),
            incomplete_coverage_segment=segment,
        )
    except ConnectorEventError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ConnectorEventError("event batch is invalid") from exc


class LifecycleEventInbox:
    """Admit lifecycle batches for exactly the cluster an enrolled observer is scoped to."""

    def __init__(
        self,
        store: LifecycleStore,
        *,
        registrations: ConnectorRegistrationReader,
        now: Callable[[], datetime],
    ) -> None:
        self._store, self._registrations, self._now = store, registrations, now

    async def _registration(self, principal_ref: str) -> ConnectorRegistration:
        registration = await self._registrations.read(principal_ref)
        if registration is None:
            raise ConnectorEventError("connector enrollment is unavailable")
        registration.admit(
            principal_ref=principal_ref,
            scope=registration.scope,
            capability=CAPABILITY,
            now=self._now(),
        )
        return registration

    async def cursor(self, principal_ref: str) -> KubernetesLifecycleCursor:
        registration = await self._registration(principal_ref)
        now = self._now()
        cursor = await self._store.acquire(
            cluster_ref=registration.scope.cluster_ref,
            holder=principal_ref,
            now=now,
            lease_until=now + timedelta(seconds=LEASE_SECONDS),
        )
        if cursor is None:
            raise ConnectorEventError("another collector holds the lifecycle lease")
        return cursor

    async def accept(self, principal_ref: str, content: bytes) -> dict[str, Any]:
        registration = await self._registration(principal_ref)
        batch = decode_batch(content, cluster_ref=registration.scope.cluster_ref)
        if not await self._store.append(batch, holder=principal_ref, now=self._now()):
            raise ConnectorEventError("event batch was not admitted")
        return {
            "schema_version": "1.0.0",
            "status": "accepted",
            "sequence": batch.expected_sequence + 1,
            "observations": len(batch.observations),
            "coverage_gap": batch.incomplete_coverage_segment is not None,
        }


class ConnectorEventTransport:
    """mTLS client for the cursor and batch routes; it follows no redirect and never retries."""

    def __init__(
        self,
        config: ConnectorTransportConfig,
        *,
        tls_context: ssl.SSLContext,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if tls_context.verify_mode != ssl.CERT_REQUIRED or not tls_context.check_hostname:
            raise ValueError("connector TLS requires certificate and hostname verification")
        self._config = config
        self._client = httpx.AsyncClient(
            transport=transport,
            verify=tls_context,
            trust_env=False,
            follow_redirects=False,
            timeout=config.timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def cursor(self) -> KubernetesLifecycleCursor:
        return decode_cursor(await self._post(CURSOR_PATH, b"{}"))

    async def send(self, batch: KubernetesLifecycleBatch) -> Mapping[str, Any]:
        value = json.loads(await self._post(BATCH_PATH, encode_batch(batch)))
        if not isinstance(value, dict) or value.get("status") != "accepted":
            raise ConnectorEventError("event acknowledgment is invalid")
        return value

    async def _post(self, path: str, body: bytes) -> bytes:
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                async with self._client.stream(
                    "POST",
                    self._config.origin.rstrip("/") + path,
                    content=body,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                ) as response:
                    if response.status_code not in {200, 201}:
                        raise ConnectorEventError("connector gateway did not accept the request")
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        content.extend(chunk)
                        if len(content) > _RESPONSE_LIMIT:
                            raise ConnectorEventError("connector response exceeds its limit")
                    return bytes(content)
        except ConnectorEventError:
            raise
        except (TimeoutError, httpx.HTTPError):
            raise ConnectorEventError("connector request failed or exceeded its deadline") from None
