"""Lease-based durable publication state for reconciliation recommendations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from fdai.shared.providers.state_store import StateStore

from .reconciliation_contracts import ReconciliationRecommendation

_MAX_CAS_ATTEMPTS = 64
_MAX_AGGREGATE_BYTES = 16 * 1_048_576
_MAX_OUTBOX_SCAN = 1000
_MAX_OUTBOX_TOTAL = 10_000
_MAX_PUBLICATION_ATTEMPTS = 32


class ReconciliationConflictError(RuntimeError):
    """A stable reconciliation identity was reused with inconsistent content."""


class ReconciliationLedgerCorruptionError(RuntimeError):
    """Durable reconciliation state failed its strict replay contract."""


class ReconciliationAggregateLimitError(RuntimeError):
    """A durable reconciliation aggregate exceeded its canonical byte ceiling."""


class ReconciliationOutboxScanLimitError(RuntimeError):
    """The durable reconciliation outbox exceeded its bounded scan ceiling."""


class ReconciliationPublicationStatus(StrEnum):
    """Durable publication state for one proposal-only recommendation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReconciliationPublication:
    """One lease-claimed outbox recommendation and broker acknowledgement."""

    recommendation: ReconciliationRecommendation
    status: ReconciliationPublicationStatus = ReconciliationPublicationStatus.PENDING
    attempts: int = 0
    available_at: datetime | None = None
    lease_until: datetime | None = None
    lease_token: str | None = None
    lease_token_hash: str | None = None
    last_error: str | None = None
    published_at: datetime | None = None
    topic: str | None = None
    partition: int | None = None
    offset: int | None = None

    def __post_init__(self) -> None:
        for value in (self.available_at, self.lease_until, self.published_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("reconciliation publication timestamps MUST be timezone-aware")
        if not 0 <= self.attempts <= _MAX_PUBLICATION_ATTEMPTS:
            raise ValueError("reconciliation publication attempts MUST be bounded")
        if self.last_error is not None and (not self.last_error or len(self.last_error) > 128):
            raise ValueError("reconciliation publication error MUST be bounded")
        if self.partition is not None and self.partition < 0:
            raise ValueError("reconciliation publication partition MUST be non-negative")
        if self.offset is not None and self.offset < 0:
            raise ValueError("reconciliation publication offset MUST be non-negative")
        if self.status is ReconciliationPublicationStatus.IN_PROGRESS and (
            self.lease_until is None or not self.lease_token_hash
        ):
            raise ValueError("in-progress reconciliation publication requires a lease token")
        if self.status is not ReconciliationPublicationStatus.IN_PROGRESS and (
            self.lease_token or self.lease_token_hash
        ):
            raise ValueError("inactive reconciliation publication cannot retain a lease token")
        if self.status is ReconciliationPublicationStatus.PUBLISHED and (
            self.published_at is None or not self.topic or self.partition is None
        ):
            raise ValueError("published reconciliation recommendation requires broker evidence")
        if self.status is ReconciliationPublicationStatus.FAILED and self.last_error is None:
            raise ValueError("failed reconciliation publication requires an error")


class InMemoryReconciliationPublicationOutbox:
    """Concurrency-safe publication state used by the reference ledger."""

    def __init__(self) -> None:
        self._publications: dict[str, ReconciliationPublication] = {}
        self._lock = asyncio.Lock()

    def register(self, recommendation: ReconciliationRecommendation) -> None:
        self._publications.setdefault(
            recommendation.idempotency_key,
            ReconciliationPublication(recommendation=recommendation),
        )

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ReconciliationPublication, ...]:
        publication_claim_bounds(now=now, limit=limit, lease_until=lease_until)
        claimed: list[ReconciliationPublication] = []
        async with self._lock:
            for key, publication in sorted(self._publications.items()):
                if len(claimed) >= limit or not publication_claimable(publication, now=now):
                    continue
                lease_token = secrets.token_urlsafe(24)
                updated = replace(
                    publication,
                    status=ReconciliationPublicationStatus.IN_PROGRESS,
                    attempts=publication.attempts + 1,
                    lease_until=lease_until,
                    lease_token=lease_token,
                    lease_token_hash=_lease_token_hash(lease_token),
                    last_error=None,
                )
                self._publications[key] = updated
                claimed.append(updated)
        return tuple(claimed)

    async def complete_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        published_at: datetime,
        topic: str,
        partition: int,
        offset: int | None,
        lease_token: str,
    ) -> None:
        del reconciliation_id
        at = aware_publication_time(published_at, "published_at")
        async with self._lock:
            current = self._require(idempotency_key)
            if current.status is ReconciliationPublicationStatus.PUBLISHED:
                if (
                    current.published_at == at
                    and current.topic == topic
                    and current.partition == partition
                    and current.offset == offset
                ):
                    return
                raise ReconciliationConflictError(
                    "published reconciliation recommendation has conflicting broker evidence"
                )
            _require_active_lease(current, "completion", lease_token=lease_token)
            self._publications[idempotency_key] = replace(
                current,
                status=ReconciliationPublicationStatus.PUBLISHED,
                lease_until=None,
                lease_token=None,
                lease_token_hash=None,
                published_at=at,
                topic=publication_text(topic, "topic"),
                partition=partition,
                offset=offset,
            )

    async def release_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        available_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        del reconciliation_id
        async with self._lock:
            current = self._require(idempotency_key)
            _require_active_lease(current, "release", lease_token=lease_token)
            self._publications[idempotency_key] = replace(
                current,
                status=ReconciliationPublicationStatus.PENDING,
                available_at=aware_publication_time(available_at, "available_at"),
                lease_until=None,
                lease_token=None,
                lease_token_hash=None,
                last_error=publication_text(error, "error"),
            )

    async def dead_letter_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        failed_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        del reconciliation_id
        aware_publication_time(failed_at, "failed_at")
        async with self._lock:
            current = self._require(idempotency_key)
            _require_active_lease(current, "dead-letter", lease_token=lease_token)
            self._publications[idempotency_key] = replace(
                current,
                status=ReconciliationPublicationStatus.FAILED,
                lease_until=None,
                lease_token=None,
                lease_token_hash=None,
                last_error=publication_text(error, "error"),
            )

    def _require(self, idempotency_key: str) -> ReconciliationPublication:
        publication = self._publications.get(idempotency_key)
        if publication is None:
            raise ReconciliationConflictError("reconciliation publication identity is unknown")
        return publication


class StateStoreReconciliationPublicationOutbox:
    """CAS-backed publication lifecycle over reconciliation aggregates."""

    _KEY_PREFIX = "ontology:reconciliation:"

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ReconciliationPublication, ...]:
        publication_claim_bounds(now=now, limit=limit, lease_until=lease_until)
        first_page, total = await self._store.read_state_page(
            self._KEY_PREFIX,
            limit=_MAX_OUTBOX_SCAN,
        )
        if total > _MAX_OUTBOX_TOTAL:
            raise ReconciliationOutboxScanLimitError(
                "reconciliation outbox exceeds its bounded scan ceiling"
            )
        rows = list(first_page)
        for offset in range(_MAX_OUTBOX_SCAN, total, _MAX_OUTBOX_SCAN):
            page, page_total = await self._store.read_state_page(
                self._KEY_PREFIX,
                limit=_MAX_OUTBOX_SCAN,
                offset=offset,
            )
            if page_total != total:
                raise ReconciliationConflictError(
                    "reconciliation outbox changed during bounded scan"
                )
            rows.extend(page)
        reconciliation_ids = sorted(
            str(row.get("reconciliation_id"))
            for row in rows
            if isinstance(row.get("reconciliation_id"), str)
        )
        claimed: list[ReconciliationPublication] = []
        for reconciliation_id in reconciliation_ids:
            if len(claimed) >= limit:
                break
            publication = await self._claim_one(
                reconciliation_id,
                now=now,
                lease_until=lease_until,
            )
            if publication is not None:
                claimed.append(publication)
        return tuple(claimed)

    async def _claim_one(
        self,
        reconciliation_id: str,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> ReconciliationPublication | None:
        key = f"{self._KEY_PREFIX}{reconciliation_id}"
        for _ in range(_MAX_CAS_ATTEMPTS):
            raw = await self._store.read_state(key)
            if raw is None:
                return None
            revision, recommendation, current, record = _parse_aggregate(
                raw,
                reconciliation_id=reconciliation_id,
            )
            if not publication_claimable(current, now=now):
                return None
            lease_token = secrets.token_urlsafe(24)
            updated = replace(
                current,
                status=ReconciliationPublicationStatus.IN_PROGRESS,
                attempts=current.attempts + 1,
                lease_until=lease_until,
                lease_token=lease_token,
                lease_token_hash=_lease_token_hash(lease_token),
                last_error=None,
            )
            next_revision = revision + 1
            record["revision"] = next_revision
            record["publication_state"] = {
                recommendation.idempotency_key: serialize_publication(updated)
            }
            _check_aggregate_size(record)
            if await self._store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision,
                audit_entry=_publication_audit_entry(
                    updated,
                    action_kind="ontology.reconciliation.publication_claimed",
                    revision=next_revision,
                ),
            ):
                return updated
        raise RuntimeError("reconciliation publication claim conflicted repeatedly")

    async def complete_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        published_at: datetime,
        topic: str,
        partition: int,
        offset: int | None,
        lease_token: str,
    ) -> None:
        await self._transition(
            reconciliation_id,
            idempotency_key,
            transition="complete",
            at=aware_publication_time(published_at, "published_at"),
            topic=publication_text(topic, "topic"),
            partition=partition,
            offset=offset,
            lease_token=lease_token,
        )

    async def release_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        available_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        await self._transition(
            reconciliation_id,
            idempotency_key,
            transition="release",
            at=aware_publication_time(available_at, "available_at"),
            error=publication_text(error, "error"),
            lease_token=lease_token,
        )

    async def dead_letter_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        failed_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        await self._transition(
            reconciliation_id,
            idempotency_key,
            transition="fail",
            at=aware_publication_time(failed_at, "failed_at"),
            error=publication_text(error, "error"),
            lease_token=lease_token,
        )

    async def _transition(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        transition: Literal["complete", "release", "fail"],
        at: datetime,
        topic: str | None = None,
        partition: int | None = None,
        offset: int | None = None,
        error: str | None = None,
        lease_token: str,
    ) -> None:
        key = f"{self._KEY_PREFIX}{reconciliation_id}"
        for _ in range(_MAX_CAS_ATTEMPTS):
            raw = await self._store.read_state(key)
            if raw is None:
                raise ReconciliationConflictError("reconciliation publication aggregate is unknown")
            revision, recommendation, current, record = _parse_aggregate(
                raw,
                reconciliation_id=reconciliation_id,
            )
            if recommendation.idempotency_key != idempotency_key:
                raise ReconciliationConflictError("reconciliation publication identity is unknown")
            if (
                transition == "complete"
                and current.status is ReconciliationPublicationStatus.PUBLISHED
            ):
                if (
                    current.published_at == at
                    and current.topic == topic
                    and current.partition == partition
                    and current.offset == offset
                ):
                    return
                raise ReconciliationConflictError(
                    "published reconciliation recommendation has conflicting broker evidence"
                )
            _require_active_lease(current, transition, lease_token=lease_token)
            if transition == "complete":
                if topic is None or partition is None:
                    raise ValueError("publication completion requires broker evidence")
                updated = replace(
                    current,
                    status=ReconciliationPublicationStatus.PUBLISHED,
                    lease_until=None,
                    lease_token=None,
                    lease_token_hash=None,
                    published_at=at,
                    topic=topic,
                    partition=partition,
                    offset=offset,
                )
                action_kind = "ontology.reconciliation.publication_completed"
            elif transition == "release":
                updated = replace(
                    current,
                    status=ReconciliationPublicationStatus.PENDING,
                    available_at=at,
                    lease_until=None,
                    lease_token=None,
                    lease_token_hash=None,
                    last_error=error,
                )
                action_kind = "ontology.reconciliation.publication_released"
            else:
                updated = replace(
                    current,
                    status=ReconciliationPublicationStatus.FAILED,
                    lease_until=None,
                    lease_token=None,
                    lease_token_hash=None,
                    last_error=error,
                )
                action_kind = "ontology.reconciliation.publication_dead_lettered"
            next_revision = revision + 1
            record["revision"] = next_revision
            record["publication_state"] = {idempotency_key: serialize_publication(updated)}
            _check_aggregate_size(record)
            if await self._store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision,
                audit_entry=_publication_audit_entry(
                    updated,
                    action_kind=action_kind,
                    revision=next_revision,
                ),
            ):
                return
        raise RuntimeError("reconciliation publication transition conflicted repeatedly")


def initial_publication_state(
    recommendation: ReconciliationRecommendation,
) -> dict[str, ReconciliationPublication]:
    return {
        recommendation.idempotency_key: ReconciliationPublication(recommendation=recommendation)
    }


def serialize_publication(publication: ReconciliationPublication) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "recommendation": publication.recommendation.model_dump(mode="json"),
        "status": publication.status.value,
        "attempts": publication.attempts,
        "available_at": _optional_timestamp(publication.available_at),
        "lease_until": _optional_timestamp(publication.lease_until),
        "lease_token_hash": publication.lease_token_hash,
        "last_error": publication.last_error,
        "published_at": _optional_timestamp(publication.published_at),
        "topic": publication.topic,
        "partition": publication.partition,
        "offset": publication.offset,
    }


def deserialize_publication(value: object) -> ReconciliationPublication:
    expected = {
        "schema_version",
        "recommendation",
        "status",
        "attempts",
        "available_at",
        "lease_until",
        "lease_token_hash",
        "last_error",
        "published_at",
        "topic",
        "partition",
        "offset",
    }
    if not isinstance(value, Mapping):
        raise ValueError("reconciliation publication state has unexpected fields")
    normalized = dict(value)
    normalized.setdefault("schema_version", "1.0.0")
    if set(normalized) != expected or normalized["schema_version"] != "1.0.0":
        raise ValueError("reconciliation publication state has unexpected fields")
    value = normalized
    attempts = value.get("attempts")
    partition = value.get("partition")
    offset = value.get("offset")
    if not isinstance(attempts, int) or isinstance(attempts, bool):
        raise ValueError("reconciliation publication attempts MUST be an integer")
    for name, item in (("partition", partition), ("offset", offset)):
        if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item < 0):
            raise ValueError(f"reconciliation publication {name} MUST be non-negative")
    last_error = value.get("last_error")
    topic = value.get("topic")
    return ReconciliationPublication(
        recommendation=ReconciliationRecommendation.model_validate(value.get("recommendation")),
        status=ReconciliationPublicationStatus(str(value.get("status"))),
        attempts=attempts,
        available_at=_parse_optional_timestamp(value.get("available_at")),
        lease_until=_parse_optional_timestamp(value.get("lease_until")),
        lease_token_hash=(
            publication_text(value.get("lease_token_hash"), "lease_token_hash")
            if value.get("lease_token_hash") is not None
            else None
        ),
        last_error=publication_text(last_error, "last_error") if last_error is not None else None,
        published_at=_parse_optional_timestamp(value.get("published_at")),
        topic=publication_text(topic, "topic") if topic is not None else None,
        partition=partition,
        offset=offset,
    )


def publication_claim_bounds(
    *,
    now: datetime,
    limit: int,
    lease_until: datetime,
) -> None:
    normalized_now = aware_publication_time(now, "now")
    normalized_lease = aware_publication_time(lease_until, "lease_until")
    if not 1 <= limit <= 100:
        raise ValueError("reconciliation publication claim limit MUST be between 1 and 100")
    if not normalized_now < normalized_lease <= normalized_now + timedelta(minutes=5):
        raise ValueError("reconciliation publication lease MUST be positive and bounded")


def publication_claimable(
    publication: ReconciliationPublication,
    *,
    now: datetime,
) -> bool:
    normalized = aware_publication_time(now, "now")
    if publication.status in {
        ReconciliationPublicationStatus.PUBLISHED,
        ReconciliationPublicationStatus.FAILED,
    }:
        return False
    if publication.available_at is not None and publication.available_at > normalized:
        return False
    return not (
        publication.status is ReconciliationPublicationStatus.IN_PROGRESS
        and publication.lease_until is not None
        and publication.lease_until > normalized
    )


def aware_publication_time(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"reconciliation publication {name} MUST be timezone-aware")
    return value.astimezone(UTC)


def publication_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"reconciliation publication {name} MUST be bounded text")
    return value


def _parse_aggregate(
    raw: Mapping[str, Any],
    *,
    reconciliation_id: str,
) -> tuple[int, ReconciliationRecommendation, ReconciliationPublication, dict[str, Any]]:
    try:
        record = json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != "1.0.0"
            or record.get("reconciliation_id") != reconciliation_id
            or not isinstance(record.get("revision"), int)
            or isinstance(record.get("revision"), bool)
            or int(record["revision"]) < 1
            or not isinstance(record.get("outbox"), dict)
            or len(record["outbox"]) != 1
        ):
            raise ValueError("invalid reconciliation publication aggregate")
        idempotency_key, payload = next(iter(record["outbox"].items()))
        recommendation = ReconciliationRecommendation.model_validate(payload)
        if idempotency_key != recommendation.idempotency_key:
            raise ValueError("reconciliation outbox identity does not match payload")
        publication_raw = record.get("publication_state", {})
        if not isinstance(publication_raw, dict):
            raise ValueError("reconciliation publication state MUST be an object")
        publication = (
            ReconciliationPublication(recommendation=recommendation)
            if not publication_raw
            else deserialize_publication(publication_raw.get(idempotency_key))
        )
        if publication.recommendation != recommendation or set(publication_raw) not in (
            set(),
            {idempotency_key},
        ):
            raise ValueError("reconciliation publication state is not bound to outbox")
        return int(record["revision"]), recommendation, publication, record
    except (TypeError, ValueError) as exc:
        raise ReconciliationLedgerCorruptionError(
            "durable reconciliation publication state failed validation"
        ) from exc


def _publication_audit_entry(
    publication: ReconciliationPublication,
    *,
    action_kind: str,
    revision: int,
) -> dict[str, Any]:
    recommendation = publication.recommendation
    return {
        "actor": "fdai.core.ontology_platform.reconciliation_outbox",
        "action_kind": action_kind,
        "reconciliation_id": recommendation.reconciliation_id,
        "recommendation_idempotency_key": recommendation.idempotency_key,
        "publication_status": publication.status.value,
        "publication_attempts": publication.attempts,
        "revision": revision,
    }


def _require_active_lease(
    publication: ReconciliationPublication,
    transition: str,
    *,
    lease_token: str,
) -> None:
    if (
        publication.status is not ReconciliationPublicationStatus.IN_PROGRESS
        or not lease_token
        or not secrets.compare_digest(
            publication.lease_token_hash or "",
            _lease_token_hash(lease_token),
        )
    ):
        raise ReconciliationConflictError(
            f"reconciliation publication {transition} requires the active lease token"
        )


def _lease_token_hash(lease_token: str) -> str:
    if not lease_token:
        raise ValueError("reconciliation publication lease token MUST be non-empty")
    return hashlib.sha256(lease_token.encode("utf-8")).hexdigest()


def _optional_timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _parse_optional_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("reconciliation publication timestamp MUST be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return aware_publication_time(parsed, "timestamp")


def _check_aggregate_size(record: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_AGGREGATE_BYTES:
        raise ReconciliationAggregateLimitError(
            "durable reconciliation aggregate exceeds its canonical byte limit"
        )


__all__ = [
    "InMemoryReconciliationPublicationOutbox",
    "ReconciliationAggregateLimitError",
    "ReconciliationConflictError",
    "ReconciliationLedgerCorruptionError",
    "ReconciliationOutboxScanLimitError",
    "ReconciliationPublication",
    "ReconciliationPublicationStatus",
    "StateStoreReconciliationPublicationOutbox",
    "aware_publication_time",
    "deserialize_publication",
    "initial_publication_state",
    "publication_claim_bounds",
    "publication_claimable",
    "publication_text",
    "serialize_publication",
]
