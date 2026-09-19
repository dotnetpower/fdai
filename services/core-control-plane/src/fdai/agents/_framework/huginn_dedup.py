"""Durable Huginn ingress deduplication with lease-fenced retries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fdai.shared.providers.state_store import StateStore

_STATE_KEY = "pantheon/huginn/ingress-dedup"
_MAX_CAS_ATTEMPTS = 8
_DEFAULT_LEASE = timedelta(seconds=60)
_MAX_LEASE = timedelta(minutes=5)


class HuginnClaimInProgressError(RuntimeError):
    """Raised so broker retry retains an ingress claim owned by another replica."""


@dataclass(frozen=True, slots=True)
class HuginnIngressClaim:
    payload: dict[str, Any]
    change_projection: dict[str, Any] | None
    duplicate: bool = False


class HuginnDedupJournal:
    """Linearize ingress keys while retaining retryable normalized payloads."""

    def __init__(
        self,
        store: StateStore,
        *,
        capacity: int,
        clock: Callable[[], datetime] | None = None,
        claim_lease: timedelta = _DEFAULT_LEASE,
    ) -> None:
        if capacity < 1:
            raise ValueError("dedup capacity MUST be positive")
        if claim_lease <= timedelta(0) or claim_lease > _MAX_LEASE:
            raise ValueError("dedup claim lease MUST be positive and at most five minutes")
        self._store = store
        self._capacity = capacity
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._claim_lease = claim_lease
        self._owner_token = uuid4().hex

    async def published_keys(self) -> tuple[str, ...]:
        """Return completed keys in oldest-to-newest sequence order."""
        _, stored_capacity, _, entries = _decode(await self._store.read_state(_STATE_KEY))
        self._validate_capacity(stored_capacity)
        return tuple(
            key
            for key, entry in sorted(entries.items(), key=lambda item: int(item[1]["sequence"]))
            if entry["status"] == "published"
        )

    async def claim(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        payload: Mapping[str, Any],
        change_projection: Mapping[str, Any] | None,
    ) -> HuginnIngressClaim:
        """Claim one key or return its completed duplicate disposition."""
        now = _clock_now(self._clock)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity)
            existing = entries.get(idempotency_key)
            if existing is not None:
                _validate_request(existing, request_digest=request_digest)
                if existing["status"] == "published":
                    return HuginnIngressClaim(payload={}, change_projection=None, duplicate=True)
                if existing["owner_token"] == self._owner_token:
                    return _claim_from_entry(existing)
                lease_expires_at = _parse_time(existing["lease_expires_at"])
                if now < lease_expires_at:
                    raise HuginnClaimInProgressError(
                        f"ingress claim remains active until {lease_expires_at.isoformat()}"
                    )
                replacement = dict(existing)
                replacement["owner_token"] = self._owner_token
                replacement["lease_expires_at"] = (now + self._claim_lease).isoformat()
                next_entries = {**entries, idempotency_key: replacement}
                if await self._advance(
                    current=current,
                    revision=revision,
                    next_sequence=next_sequence,
                    entries=next_entries,
                    audit={
                        "actor": "Huginn",
                        "action_kind": "ingress.claim.recovered",
                        "idempotency_key": idempotency_key,
                        "request_digest": request_digest,
                        "revision": revision + 1,
                    },
                ):
                    return _claim_from_entry(replacement)
                continue

            next_entries = dict(entries)
            if len(next_entries) >= self._capacity:
                evictable = sorted(
                    (
                        (key, entry)
                        for key, entry in next_entries.items()
                        if entry["status"] == "published"
                    ),
                    key=lambda item: int(item[1]["sequence"]),
                )
                if not evictable:
                    raise RuntimeError("Huginn dedup journal has no completed entry to evict")
                del next_entries[evictable[0][0]]
            normalized_payload = _json_mapping(payload, field="payload")
            normalized_change = (
                _json_mapping(change_projection, field="change_projection")
                if change_projection is not None
                else None
            )
            entry = {
                "request_digest": request_digest,
                "status": "pending",
                "owner_token": self._owner_token,
                "lease_expires_at": (now + self._claim_lease).isoformat(),
                "sequence": next_sequence,
                "payload": normalized_payload,
                "change_projection": normalized_change,
            }
            next_entries[idempotency_key] = entry
            if await self._advance(
                current=current,
                revision=revision,
                next_sequence=next_sequence + 1,
                entries=next_entries,
                audit={
                    "actor": "Huginn",
                    "action_kind": "ingress.claim.created",
                    "idempotency_key": idempotency_key,
                    "request_digest": request_digest,
                    "revision": revision + 1,
                },
            ):
                return _claim_from_entry(entry)
        raise RuntimeError("Huginn dedup claim contention exceeded the bounded retry limit")

    async def complete(self, *, idempotency_key: str, request_digest: str) -> None:
        """Checkpoint successful publication without retaining the payload body."""
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity)
            existing = entries.get(idempotency_key)
            if existing is None:
                raise RuntimeError("Huginn ingress claim disappeared before completion")
            _validate_request(existing, request_digest=request_digest)
            if existing["status"] == "published":
                return
            if existing["owner_token"] != self._owner_token:
                raise HuginnClaimInProgressError("Huginn ingress claim belongs to another replica")
            completed = {
                "request_digest": request_digest,
                "status": "published",
                "owner_token": "",
                "lease_expires_at": "",
                "sequence": existing["sequence"],
                "payload": None,
                "change_projection": None,
            }
            if await self._advance(
                current=current,
                revision=revision,
                next_sequence=next_sequence,
                entries={**entries, idempotency_key: completed},
                audit={
                    "actor": "Huginn",
                    "action_kind": "ingress.claim.published",
                    "idempotency_key": idempotency_key,
                    "request_digest": request_digest,
                    "revision": revision + 1,
                },
            ):
                return
        raise RuntimeError("Huginn dedup completion contention exceeded the bounded retry limit")

    async def _advance(
        self,
        *,
        current: Mapping[str, Any] | None,
        revision: int,
        next_sequence: int,
        entries: Mapping[str, Mapping[str, Any]],
        audit: Mapping[str, Any],
    ) -> bool:
        value = _encode(
            revision=revision + 1,
            capacity=self._capacity,
            next_sequence=next_sequence,
            entries=entries,
        )
        if current is None:
            return await self._store.write_state_with_audit_if_absent(_STATE_KEY, value, audit)
        return await self._store.compare_and_set_state_with_audit(
            _STATE_KEY,
            value,
            expected_revision=revision,
            audit_entry=audit,
        )

    def _validate_capacity(self, stored_capacity: int | None) -> None:
        if stored_capacity is not None and stored_capacity != self._capacity:
            raise ValueError("Huginn dedup capacity conflicts with durable state")


def request_digest(raw: Mapping[str, Any]) -> str:
    """Return the canonical identity of one raw ingress request."""
    try:
        encoded = json.dumps(
            raw,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("raw ingress request MUST be canonical JSON") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _decode(
    record: Mapping[str, Any] | None,
) -> tuple[int, int | None, int, dict[str, dict[str, Any]]]:
    if record is None:
        return 0, None, 1, {}
    revision = record.get("revision")
    capacity = record.get("capacity")
    next_sequence = record.get("next_sequence")
    raw_entries = record.get("entries")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Huginn dedup revision MUST be positive")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        raise ValueError("Huginn dedup capacity MUST be positive")
    if isinstance(next_sequence, bool) or not isinstance(next_sequence, int) or next_sequence < 1:
        raise ValueError("Huginn dedup next sequence MUST be positive")
    if not isinstance(raw_entries, Mapping) or len(raw_entries) > capacity:
        raise ValueError("Huginn dedup entries are malformed")
    entries: dict[str, dict[str, Any]] = {}
    sequences: set[int] = set()
    for key, raw_entry in raw_entries.items():
        if not isinstance(key, str) or not key or not isinstance(raw_entry, Mapping):
            raise ValueError("Huginn dedup entry is malformed")
        entry = dict(raw_entry)
        digest = entry.get("request_digest")
        status = entry.get("status")
        sequence = entry.get("sequence")
        if (
            not _is_digest(digest)
            or status not in {"pending", "published"}
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
            or sequence in sequences
            or sequence >= next_sequence
        ):
            raise ValueError("Huginn dedup entry identity is malformed")
        sequences.add(sequence)
        if status == "pending":
            if (
                not isinstance(entry.get("owner_token"), str)
                or not entry["owner_token"]
                or not isinstance(entry.get("lease_expires_at"), str)
                or not isinstance(entry.get("payload"), Mapping)
                or entry.get("change_projection") is not None
                and not isinstance(entry.get("change_projection"), Mapping)
            ):
                raise ValueError("Huginn pending dedup entry is malformed")
            _parse_time(entry["lease_expires_at"])
        elif any(
            (
                entry.get("owner_token") != "",
                entry.get("lease_expires_at") != "",
                entry.get("payload") is not None,
                entry.get("change_projection") is not None,
            )
        ):
            raise ValueError("Huginn published dedup entry retains pending state")
        entries[key] = entry
    return revision, capacity, next_sequence, entries


def _encode(
    *,
    revision: int,
    capacity: int,
    next_sequence: int,
    entries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "capacity": capacity,
        "next_sequence": next_sequence,
        "entries": {key: dict(entries[key]) for key in sorted(entries)},
    }


def _claim_from_entry(entry: Mapping[str, Any]) -> HuginnIngressClaim:
    payload = _json_mapping(entry.get("payload"), field="payload")
    raw_change = entry.get("change_projection")
    change = (
        _json_mapping(raw_change, field="change_projection") if raw_change is not None else None
    )
    return HuginnIngressClaim(payload=payload, change_projection=change)


def _validate_request(entry: Mapping[str, Any], *, request_digest: str) -> None:
    if entry.get("request_digest") != request_digest:
        raise ValueError("Huginn idempotency key collides with another raw request")


def _json_mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Huginn dedup {field} MUST be an object")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Huginn dedup {field} MUST be canonical JSON") from exc
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError(f"Huginn dedup {field} MUST be an object")
    return decoded


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Huginn dedup clock MUST be timezone-aware")
    return now.astimezone(UTC)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Huginn dedup lease timestamp is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Huginn dedup lease timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


__all__ = [
    "HuginnClaimInProgressError",
    "HuginnDedupJournal",
    "HuginnIngressClaim",
    "request_digest",
]
