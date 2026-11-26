"""Durable ownership-fenced pending effects for MSCP observation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.core.mscp_profile.effect_verification import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
)
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "mscp:pending-effect:"
_SCHEMA_VERSION = "1.1.0"
_MAX_DUE_READ = 10_000
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class PendingEffectStatus(StrEnum):
    """Durable lifecycle of one expected effect."""

    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"


class PendingEffectConflictError(RuntimeError):
    """A prediction identity was reused with different immutable content."""


class PendingEffectStaleRevisionError(RuntimeError):
    """A caller attempted to update a non-current revision."""


class PendingEffectOwnershipError(RuntimeError):
    """A caller does not own the current observation lease."""


@dataclass(frozen=True, slots=True)
class PendingEffectRecord:
    """One restart-safe expected effect and its observation ownership fence."""

    expected: ExpectedEffect
    action_type: str
    environment: str
    observer_version: str
    effect_digest: str
    status: PendingEffectStatus = PendingEffectStatus.PENDING
    revision: int = 1
    owner_id: str | None = None
    owner_generation: int = 0
    lease_until: datetime | None = None
    completed_at: datetime | None = None
    verification_status: EffectVerificationStatus | None = None
    verification_reason: EffectVerificationReason | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("action_type", self.action_type),
            ("environment", self.environment),
            ("observer_version", self.observer_version),
        ):
            if not value.strip() or len(value) > 256:
                raise ValueError(f"PendingEffectRecord.{name} MUST be bounded non-empty text")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or isinstance(self.owner_generation, bool)
            or not isinstance(self.owner_generation, int)
            or self.revision < 1
            or self.owner_generation < 0
        ):
            raise ValueError("pending effect revisions MUST be non-negative and current")
        if _DIGEST.fullmatch(self.effect_digest) is None:
            raise ValueError("pending effect digest MUST be a SHA-256 digest")
        if self.effect_digest != _effect_digest(
            self.expected,
            action_type=self.action_type,
            environment=self.environment,
            observer_version=self.observer_version,
        ):
            raise ValueError("pending effect digest does not match immutable content")
        if self.status is PendingEffectStatus.PENDING:
            if any(
                value is not None for value in (self.owner_id, self.lease_until, self.completed_at)
            ):
                raise ValueError("pending effect MUST NOT carry ownership or completion")
            if self.verification_status is not None or self.verification_reason is not None:
                raise ValueError("pending effect MUST NOT carry verification")
        elif self.status is PendingEffectStatus.CLAIMED:
            if self.owner_id is None or self.lease_until is None or self.completed_at is not None:
                raise ValueError("claimed effect requires one active owner lease")
            if self.verification_status is not None or self.verification_reason is not None:
                raise ValueError("claimed effect MUST NOT carry verification")
            _require_owner(self.owner_id)
            _require_aware("lease_until", self.lease_until)
        elif self.status is PendingEffectStatus.COMPLETED:
            if self.owner_id is None or self.lease_until is None or self.completed_at is None:
                raise ValueError("completed effect requires retained ownership and completion")
            _require_owner(self.owner_id)
            _require_aware("lease_until", self.lease_until)
            _require_aware("completed_at", self.completed_at)
            if self.completed_at > self.lease_until:
                raise ValueError("completed effect MUST remain inside its owner lease")
            if self.verification_status is None or self.verification_reason is None:
                raise ValueError("completed effect requires one verification result")

    def to_mapping(self) -> dict[str, object]:
        """Return a strict state-store representation."""

        return {
            "schema_version": _SCHEMA_VERSION,
            "prediction_id": self.expected.prediction_id,
            "target_ref": self.expected.target_ref,
            "metric": self.expected.metric,
            "acceptable_min": self.expected.acceptable_min,
            "acceptable_max": self.expected.acceptable_max,
            "predicted_at": _timestamp(self.expected.predicted_at),
            "observation_deadline": _timestamp(self.expected.observation_deadline),
            "action_type": self.action_type,
            "environment": self.environment,
            "observer_version": self.observer_version,
            "effect_digest": self.effect_digest,
            "status": self.status.value,
            "revision": self.revision,
            "owner_id": self.owner_id,
            "owner_generation": self.owner_generation,
            "lease_until": _timestamp(self.lease_until),
            "completed_at": _timestamp(self.completed_at),
            "verification_status": (
                self.verification_status.value if self.verification_status is not None else None
            ),
            "verification_reason": (
                self.verification_reason.value if self.verification_reason is not None else None
            ),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PendingEffectRecord:
        """Decode one exact durable row and reject partial state."""

        base_keys = {
            "schema_version",
            "prediction_id",
            "target_ref",
            "metric",
            "acceptable_min",
            "acceptable_max",
            "predicted_at",
            "observation_deadline",
            "action_type",
            "environment",
            "observer_version",
            "effect_digest",
            "status",
            "revision",
            "owner_id",
            "owner_generation",
            "lease_until",
            "completed_at",
        }
        verification_keys = {
            "verification_status",
            "verification_reason",
        }
        schema_version = value.get("schema_version")
        expected_keys = (
            base_keys | verification_keys
            if schema_version == _SCHEMA_VERSION
            else base_keys
            if schema_version == "1.0.0"
            else set()
        )
        if set(value) != expected_keys:
            raise ValueError("pending effect state has an unsupported schema")
        return cls(
            expected=ExpectedEffect(
                prediction_id=_string(value, "prediction_id"),
                target_ref=_string(value, "target_ref"),
                metric=_string(value, "metric"),
                acceptable_min=_number(value, "acceptable_min"),
                acceptable_max=_number(value, "acceptable_max"),
                predicted_at=_instant(value, "predicted_at"),
                observation_deadline=_instant(value, "observation_deadline"),
            ),
            action_type=_string(value, "action_type"),
            environment=_string(value, "environment"),
            observer_version=_string(value, "observer_version"),
            effect_digest=_string(value, "effect_digest"),
            status=PendingEffectStatus(_string(value, "status")),
            revision=_integer(value, "revision"),
            owner_id=_optional_string(value, "owner_id"),
            owner_generation=_integer(value, "owner_generation"),
            lease_until=_optional_instant(value, "lease_until"),
            completed_at=_optional_instant(value, "completed_at"),
            verification_status=(
                _optional_enum(value, "verification_status", EffectVerificationStatus)
                if schema_version == _SCHEMA_VERSION
                else None
            ),
            verification_reason=(
                _optional_enum(value, "verification_reason", EffectVerificationReason)
                if schema_version == _SCHEMA_VERSION
                else None
            ),
        )


class StateStorePendingEffectStore:
    """Persist pending effects with compare-and-set observation ownership."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def register(
        self,
        expected: ExpectedEffect,
        *,
        action_type: str,
        environment: str,
        observer_version: str,
    ) -> PendingEffectRecord:
        """Create one immutable effect or return its exact idempotent replay."""

        record = PendingEffectRecord(
            expected=expected,
            action_type=action_type,
            environment=environment,
            observer_version=observer_version,
            effect_digest=_effect_digest(
                expected,
                action_type=action_type,
                environment=environment,
                observer_version=observer_version,
            ),
        )
        key = _state_key(expected.prediction_id)
        created = await self._state_store.write_state_with_audit_if_absent(
            key,
            record.to_mapping(),
            _audit("registered", record),
        )
        if created:
            return record
        existing = await self.get(expected.prediction_id)
        if existing.effect_digest != record.effect_digest:
            raise PendingEffectConflictError(
                "prediction identity was reused with different expected effect content"
            )
        return existing

    async def get(self, prediction_id: str) -> PendingEffectRecord:
        """Load one prediction or raise when it is absent."""

        value = await self._state_store.read_state(_state_key(prediction_id))
        if value is None:
            raise KeyError(prediction_id)
        return PendingEffectRecord.from_mapping(value)

    async def list_ready(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[PendingEffectRecord, ...]:
        """Return deadline-ordered unowned or expired effects ready to observe."""

        _require_aware("now", now)
        if not 1 <= limit <= _MAX_DUE_READ:
            raise ValueError(f"limit MUST be between 1 and {_MAX_DUE_READ}")
        values, total = await self._state_store.read_state_page(
            _STATE_PREFIX,
            limit=_MAX_DUE_READ,
        )
        if total > _MAX_DUE_READ:
            raise ValueError("pending effect ready scan exceeds its bounded state window")
        records = tuple(PendingEffectRecord.from_mapping(value) for value in values)
        ready = (
            record
            for record in records
            if record.expected.predicted_at <= now
            and (
                record.status is PendingEffectStatus.PENDING
                or (
                    record.status is PendingEffectStatus.CLAIMED
                    and record.lease_until is not None
                    and record.lease_until <= now
                )
            )
        )
        return tuple(
            sorted(
                ready,
                key=lambda record: (
                    record.expected.observation_deadline,
                    record.expected.prediction_id,
                ),
            )[:limit]
        )

    async def claim(
        self,
        prediction_id: str,
        *,
        owner_id: str,
        expected_revision: int,
        now: datetime,
        lease_until: datetime,
    ) -> PendingEffectRecord:
        """Acquire one current or expired effect with a generation fence."""

        _require_owner(owner_id)
        _require_aware("now", now)
        _require_aware("lease_until", lease_until)
        if lease_until <= now:
            raise ValueError("lease_until MUST be later than now")
        current = await self.get(prediction_id)
        if current.revision != expected_revision:
            raise PendingEffectStaleRevisionError("pending effect revision is stale")
        if current.expected.predicted_at > now:
            raise PendingEffectOwnershipError("pending effect is not ready to observe")
        if current.status is PendingEffectStatus.COMPLETED:
            raise PendingEffectOwnershipError("completed effect cannot be claimed")
        if (
            current.status is PendingEffectStatus.CLAIMED
            and current.lease_until is not None
            and current.lease_until > now
        ):
            raise PendingEffectOwnershipError("pending effect already has an active owner")
        updated = replace(
            current,
            status=PendingEffectStatus.CLAIMED,
            revision=current.revision + 1,
            owner_id=owner_id,
            owner_generation=current.owner_generation + 1,
            lease_until=lease_until,
            completed_at=None,
        )
        return await self._compare_and_set(current, updated, event="claimed")

    async def complete(
        self,
        prediction_id: str,
        *,
        owner_id: str,
        owner_generation: int,
        expected_revision: int,
        completed_at: datetime,
        result: EffectVerificationResult,
    ) -> PendingEffectRecord:
        """Complete only the live owner generation before its lease expires."""

        _require_owner(owner_id)
        _require_aware("completed_at", completed_at)
        current = await self.get(prediction_id)
        if current.revision != expected_revision:
            raise PendingEffectStaleRevisionError("pending effect revision is stale")
        if (
            current.status is not PendingEffectStatus.CLAIMED
            or current.owner_id != owner_id
            or current.owner_generation != owner_generation
            or current.lease_until is None
            or completed_at > current.lease_until
        ):
            raise PendingEffectOwnershipError("pending effect ownership fence is stale")
        updated = replace(
            current,
            status=PendingEffectStatus.COMPLETED,
            revision=current.revision + 1,
            completed_at=completed_at,
            verification_status=result.status,
            verification_reason=result.reason,
        )
        return await self._compare_and_set(current, updated, event="completed")

    async def _compare_and_set(
        self,
        current: PendingEffectRecord,
        updated: PendingEffectRecord,
        *,
        event: str,
    ) -> PendingEffectRecord:
        written = await self._state_store.compare_and_set_state_with_audit(
            _state_key(current.expected.prediction_id),
            updated.to_mapping(),
            expected_revision=current.revision,
            audit_entry=_audit(event, updated),
        )
        if not written:
            raise PendingEffectStaleRevisionError("pending effect changed concurrently")
        return updated


def _effect_digest(
    expected: ExpectedEffect,
    *,
    action_type: str,
    environment: str,
    observer_version: str,
) -> str:
    payload = {
        "prediction_id": expected.prediction_id,
        "target_ref": expected.target_ref,
        "metric": expected.metric,
        "acceptable_min": expected.acceptable_min,
        "acceptable_max": expected.acceptable_max,
        "predicted_at": _timestamp(expected.predicted_at),
        "observation_deadline": _timestamp(expected.observation_deadline),
        "action_type": action_type,
        "environment": environment,
        "observer_version": observer_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _state_key(prediction_id: str) -> str:
    if not prediction_id.strip():
        raise ValueError("prediction_id MUST be non-empty")
    return _STATE_PREFIX + hashlib.sha256(prediction_id.encode()).hexdigest()


def _audit(event: str, record: PendingEffectRecord) -> dict[str, object]:
    return {
        "kind": f"mscp.pending_effect.{event}",
        "prediction_digest": hashlib.sha256(record.expected.prediction_id.encode()).hexdigest(),
        "effect_digest": record.effect_digest,
        "status": record.status.value,
        "revision": record.revision,
        "owner_generation": record.owner_generation,
    }


def _require_owner(value: str) -> None:
    if not value.strip() or len(value) > 256:
        raise ValueError("owner_id MUST be bounded non-empty text")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"pending effect {key} MUST be non-empty text")
    return item


def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise ValueError(f"pending effect {key} MUST be text or null")
    return item


def _number(value: Mapping[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise ValueError(f"pending effect {key} MUST be numeric")
    return float(item)


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"pending effect {key} MUST be an integer")
    return item


def _instant(value: Mapping[str, Any], key: str) -> datetime:
    item = _string(value, key)
    parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
    _require_aware(key, parsed)
    return parsed


def _optional_instant(value: Mapping[str, Any], key: str) -> datetime | None:
    item = value.get(key)
    if item is None:
        return None
    return _instant(value, key)


def _optional_enum[EnumType: StrEnum](
    value: Mapping[str, Any],
    key: str,
    enum_type: type[EnumType],
) -> EnumType | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"pending effect {key} MUST be text or null")
    return enum_type(item)


__all__ = [
    "PendingEffectConflictError",
    "PendingEffectOwnershipError",
    "PendingEffectRecord",
    "PendingEffectStaleRevisionError",
    "PendingEffectStatus",
    "StateStorePendingEffectStore",
]
