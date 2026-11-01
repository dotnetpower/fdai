"""Persistence and read-boundary expiry enforcement for content-free production shadow rows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .semantic_production_shadow import (
    PRODUCTION_SHADOW_ABSENT,
    PRODUCTION_SHADOW_LINKED,
    ProductionShadowRecord,
)

PRODUCTION_SHADOW_KEY_PREFIX = "production_shadow:record:"
MAX_CLEANUP_BATCH_LIMIT = 10_000
_ALLOWED_RECORD_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_HEX_CHARS = frozenset("0123456789abcdef")
_ALLOWED_DISPOSITIONS = frozenset(
    {
        PRODUCTION_SHADOW_ABSENT,
        PRODUCTION_SHADOW_LINKED,
        "held",
        "clarification",
        "unavailable",
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware_timestamp(value: datetime, *, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} MUST be a timezone-aware datetime")
    return value.astimezone(UTC)


def _validate_digest_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(
            f"{field_name} MUST be a content-free sha256 digest (sha256:<hex>), got invalid value"
        )
    hex_part = value.removeprefix("sha256:")
    if not (8 <= len(hex_part) <= 64 and all(ch in _HEX_CHARS for ch in hex_part)):
        raise ValueError(
            f"{field_name} MUST be a content-free sha256 digest (sha256:<hex>), got invalid value"
        )
    return value


def _validate_record_identifier(record_id: str) -> str:
    if (
        not isinstance(record_id, str)
        or not (1 <= len(record_id) <= 128)
        or not all(ch in _ALLOWED_RECORD_ID_CHARS for ch in record_id)
    ):
        raise ValueError(
            "production shadow record_id MUST be 1-128 ASCII identifier characters without colons"
        )
    return record_id


def _validate_shadow_storage_key(key: str) -> str:
    if not isinstance(key, str) or not key.startswith(PRODUCTION_SHADOW_KEY_PREFIX):
        raise ValueError(
            f"storage key MUST start with '{PRODUCTION_SHADOW_KEY_PREFIX}'; "
            "authoritative state keys are off-limits"
        )
    suffix = key.removeprefix(PRODUCTION_SHADOW_KEY_PREFIX)
    _validate_record_identifier(suffix)
    return key


@dataclass(frozen=True, slots=True, init=False)
class SemanticProductionShadowRecord:
    """Content-free production-shadow record with explicit expiry metadata."""

    record_id: str
    record_digest: str
    turn_digest: str
    disposition: str
    expires_at: datetime
    carried_form_digest: str | None
    execution_authority: bool

    def __init__(
        self,
        record_id: str = "",
        record_digest: str = "",
        turn_digest: str = "",
        disposition: str = PRODUCTION_SHADOW_LINKED,
        expires_at: datetime | None = None,
        *,
        carried_form_digest: str | None = None,
        execution_authority: bool = False,
    ) -> None:
        if execution_authority is not False:
            raise ValueError("production shadow record MUST NOT carry execution authority")
        validated_record_digest = _validate_digest_token(record_digest, field_name="record_digest")
        validated_turn_digest = _validate_digest_token(turn_digest, field_name="turn_digest")
        effective_id = (
            record_id if record_id else validated_record_digest.removeprefix("sha256:")[:24]
        )
        validated_id = _validate_record_identifier(effective_id)
        if disposition not in _ALLOWED_DISPOSITIONS:
            raise ValueError(f"unsupported production shadow disposition: {disposition!r}")
        if expires_at is None:
            raise ValueError("expires_at is required for production shadow records")
        validated_expires_at = _ensure_aware_timestamp(expires_at, label="expires_at")
        validated_carried = (
            _validate_digest_token(carried_form_digest, field_name="carried_form_digest")
            if carried_form_digest is not None
            else None
        )
        object.__setattr__(self, "record_id", validated_id)
        object.__setattr__(self, "record_digest", validated_record_digest)
        object.__setattr__(self, "turn_digest", validated_turn_digest)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "expires_at", validated_expires_at)
        object.__setattr__(self, "carried_form_digest", validated_carried)
        object.__setattr__(self, "execution_authority", False)

    @property
    def storage_key(self) -> str:
        return f"{PRODUCTION_SHADOW_KEY_PREFIX}{self.record_id}"

    def as_state(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "record_digest": self.record_digest,
            "turn_digest": self.turn_digest,
            "disposition": self.disposition,
            "expires_at": self.expires_at.isoformat(),
            "carried_form_digest": self.carried_form_digest,
            "execution_authority": False,
        }

    @classmethod
    def from_state(cls, payload: Mapping[str, Any]) -> SemanticProductionShadowRecord:
        allowed_keys = {
            "record_id",
            "record_digest",
            "turn_digest",
            "disposition",
            "expires_at",
            "carried_form_digest",
            "execution_authority",
        }
        unexpected = set(payload.keys()) - allowed_keys
        if unexpected:
            raise ValueError(
                f"stored shadow state contains non-allowlisted fields: {sorted(unexpected)}"
            )
        raw_expires = payload.get("expires_at")
        if isinstance(raw_expires, str):
            parsed_expires = datetime.fromisoformat(raw_expires)
        elif isinstance(raw_expires, datetime):
            parsed_expires = raw_expires
        else:
            raise ValueError("stored shadow state expires_at MUST be ISO-8601 string or datetime")
        carried = payload.get("carried_form_digest")
        return cls(
            record_id=str(payload.get("record_id") or ""),
            record_digest=str(payload.get("record_digest") or ""),
            turn_digest=str(payload.get("turn_digest") or ""),
            disposition=str(payload.get("disposition") or ""),
            expires_at=parsed_expires,
            carried_form_digest=str(carried) if carried is not None else None,
            execution_authority=bool(payload.get("execution_authority", False)),
        )

    @classmethod
    def from_production_shadow_record(
        cls,
        record: ProductionShadowRecord,
        *,
        record_id: str | None = None,
    ) -> SemanticProductionShadowRecord:
        derived_id = (
            record_id
            if record_id is not None
            else record.sample_id_digest.removeprefix("sha256:")[:24]
        )
        return cls(
            record_id=derived_id,
            record_digest=record.answer_output_digest,
            turn_digest=record.judgment_request_digest,
            disposition=record.disposition,
            expires_at=record.expires_at,
            carried_form_digest=record.carried_form_digest,
            execution_authority=record.execution_authority,
        )


@dataclass(frozen=True, slots=True)
class ProductionShadowCleanupReceipt:
    """Bounded cleanup receipt proving only expired shadow keys were removed."""

    evaluated_at: datetime
    scanned_shadow_keys: int
    deleted_count: int
    deleted_keys: tuple[str, ...]
    remaining_expired_count: int
    active_count: int
    skipped_non_shadow_keys: int


class ExpiringProductionShadowStore:
    """Enforce production-shadow TTL at both read and bounded-cleanup boundaries.

    All shadow records live strictly under ``production_shadow:record:<record_id>``.
    Expired rows are withheld immediately on ``get`` and ``list_active`` before any
    cleanup runs, and ``cleanup_expired`` refuses to touch keys outside the shadow
    prefix so authoritative state can never be deleted.
    """

    def __init__(
        self,
        clock: Callable[[], datetime] = _utc_now,
        *,
        backing_store: MutableMapping[str, Any] | None = None,
    ) -> None:
        self._clock = clock
        self._backing: MutableMapping[str, Any] = backing_store if backing_store is not None else {}

    @property
    def backing_store(self) -> MutableMapping[str, Any]:
        return self._backing

    def record(
        self,
        shadow_record: SemanticProductionShadowRecord | ProductionShadowRecord,
        *,
        now: datetime | None = None,
    ) -> SemanticProductionShadowRecord:
        check_time = _ensure_aware_timestamp(
            now if now is not None else self._clock(), label="clock"
        )
        normalized = (
            SemanticProductionShadowRecord.from_production_shadow_record(shadow_record)
            if isinstance(shadow_record, ProductionShadowRecord)
            else shadow_record
        )
        if not isinstance(normalized, SemanticProductionShadowRecord):
            raise TypeError(
                "shadow_record MUST be a SemanticProductionShadowRecord or ProductionShadowRecord"
            )
        if normalized.expires_at <= check_time:
            raise ValueError("production shadow record is already expired at write time")
        key = _validate_shadow_storage_key(normalized.storage_key)
        self._backing[key] = normalized.as_state()
        return normalized

    def get(
        self,
        record_id: str,
        *,
        now: datetime | None = None,
    ) -> SemanticProductionShadowRecord | None:
        check_time = _ensure_aware_timestamp(
            now if now is not None else self._clock(), label="clock"
        )
        if record_id.startswith(PRODUCTION_SHADOW_KEY_PREFIX):
            key = _validate_shadow_storage_key(record_id)
        else:
            validated_id = _validate_record_identifier(record_id)
            key = f"{PRODUCTION_SHADOW_KEY_PREFIX}{validated_id}"
        raw = self._backing.get(key)
        if not isinstance(raw, Mapping):
            return None
        try:
            stored = SemanticProductionShadowRecord.from_state(raw)
        except ValueError:
            return None
        if stored.expires_at <= check_time:
            return None
        return stored

    def list_active(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[SemanticProductionShadowRecord, ...]:
        check_time = _ensure_aware_timestamp(
            now if now is not None else self._clock(), label="clock"
        )
        active: list[SemanticProductionShadowRecord] = []
        for key, raw in list(self._backing.items()):
            if not isinstance(key, str) or not key.startswith(PRODUCTION_SHADOW_KEY_PREFIX):
                continue
            _validate_shadow_storage_key(key)
            if not isinstance(raw, Mapping):
                continue
            try:
                stored = SemanticProductionShadowRecord.from_state(raw)
            except ValueError:
                continue
            if stored.expires_at > check_time:
                active.append(stored)
        active.sort(key=lambda item: (item.expires_at, item.record_id))
        return tuple(active)

    def cleanup_expired(
        self,
        *,
        max_delete: int = 100,
        now: datetime | None = None,
    ) -> ProductionShadowCleanupReceipt:
        if type(max_delete) is not int or not 1 <= max_delete <= MAX_CLEANUP_BATCH_LIMIT:
            raise ValueError(
                f"max_delete MUST be an integer between 1 and {MAX_CLEANUP_BATCH_LIMIT}"
            )
        check_time = _ensure_aware_timestamp(
            now if now is not None else self._clock(), label="clock"
        )
        scanned_shadow_keys = 0
        skipped_non_shadow_keys = 0
        active_count = 0
        expired_candidates: list[tuple[datetime, str]] = []

        for key, raw in list(self._backing.items()):
            if not isinstance(key, str) or not key.startswith(PRODUCTION_SHADOW_KEY_PREFIX):
                skipped_non_shadow_keys += 1
                continue
            _validate_shadow_storage_key(key)
            scanned_shadow_keys += 1
            if not isinstance(raw, Mapping):
                expired_candidates.append((datetime.min.replace(tzinfo=UTC), key))
                continue
            try:
                stored = SemanticProductionShadowRecord.from_state(raw)
            except ValueError:
                expired_candidates.append((datetime.min.replace(tzinfo=UTC), key))
                continue
            if stored.expires_at <= check_time:
                expired_candidates.append((stored.expires_at, key))
            else:
                active_count += 1

        expired_candidates.sort(key=lambda pair: (pair[0], pair[1]))
        to_delete = expired_candidates[:max_delete]
        deleted_keys: list[str] = []
        for _, shadow_key in to_delete:
            validated_key = _validate_shadow_storage_key(shadow_key)
            self._backing.pop(validated_key, None)
            deleted_keys.append(validated_key)

        remaining_expired_count = len(expired_candidates) - len(deleted_keys)
        return ProductionShadowCleanupReceipt(
            evaluated_at=check_time,
            scanned_shadow_keys=scanned_shadow_keys,
            deleted_count=len(deleted_keys),
            deleted_keys=tuple(deleted_keys),
            remaining_expired_count=remaining_expired_count,
            active_count=active_count,
            skipped_non_shadow_keys=skipped_non_shadow_keys,
        )


__all__ = [
    "MAX_CLEANUP_BATCH_LIMIT",
    "PRODUCTION_SHADOW_KEY_PREFIX",
    "ExpiringProductionShadowStore",
    "ProductionShadowCleanupReceipt",
    "SemanticProductionShadowRecord",
]
