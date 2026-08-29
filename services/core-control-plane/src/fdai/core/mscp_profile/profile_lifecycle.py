"""Durable reviewed lifecycle for MSCP shadow and gating profile state."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from fdai.core.mscp_profile.readiness import MscpCandidateKey, MscpReadinessReport
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "mscp:profile-lifecycle:"
_SCHEMA_VERSION = "1.0.0"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class MscpProfileMode(StrEnum):
    """Profile evidence mode, independent from runtime action authority."""

    SHADOW = "shadow"
    GATING = "gating"


class MscpProfileLifecycleConflictError(RuntimeError):
    """A lifecycle revision or reviewed evidence fence is stale."""


@dataclass(frozen=True, slots=True)
class IndependentProfileReview:
    """One external review bound to an exact readiness report digest."""

    review_id: str
    reviewer_id: str
    candidate: MscpCandidateKey
    readiness_digest: str
    reviewed_at: datetime
    approved: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("review_id", self.review_id),
            ("reviewer_id", self.reviewer_id),
        ):
            if not value.strip() or len(value) > 256:
                raise ValueError(f"IndependentProfileReview.{name} MUST be bounded text")
        if _DIGEST.fullmatch(self.readiness_digest) is None:
            raise ValueError("IndependentProfileReview.readiness_digest MUST be SHA-256")
        _require_aware("reviewed_at", self.reviewed_at)
        if not isinstance(self.approved, bool):
            raise ValueError("IndependentProfileReview.approved MUST be a boolean")


@dataclass(frozen=True, slots=True)
class MscpProfileLifecycleRecord:
    """Current durable profile state without runtime activation authority."""

    candidate: MscpCandidateKey
    mode: MscpProfileMode
    revision: int
    updated_at: datetime
    readiness_digest: str | None = None
    review_id: str | None = None
    transition_reason: str = "registered_shadow"
    activation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("MSCP profile lifecycle revision MUST be positive")
        _require_aware("updated_at", self.updated_at)
        if not self.transition_reason.strip() or len(self.transition_reason) > 256:
            raise ValueError("transition_reason MUST be bounded non-empty text")
        if self.activation_authority:
            raise ValueError("MSCP profile lifecycle MUST NOT grant activation authority")
        if self.mode is MscpProfileMode.GATING and (
            self.readiness_digest is None or self.review_id is None
        ):
            raise ValueError("gating mode requires exact readiness and review evidence")
        if self.readiness_digest is not None and _DIGEST.fullmatch(self.readiness_digest) is None:
            raise ValueError("readiness_digest MUST be SHA-256 or null")

    def to_mapping(self) -> dict[str, object]:
        """Return the strict durable state representation."""

        return {
            "schema_version": _SCHEMA_VERSION,
            "candidate": asdict(self.candidate),
            "mode": self.mode.value,
            "revision": self.revision,
            "updated_at": self.updated_at.astimezone(UTC).isoformat(),
            "readiness_digest": self.readiness_digest,
            "review_id": self.review_id,
            "transition_reason": self.transition_reason,
            "activation_authority": False,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MscpProfileLifecycleRecord:
        """Decode one exact state row and reject malformed authority."""

        keys = {
            "schema_version",
            "candidate",
            "mode",
            "revision",
            "updated_at",
            "readiness_digest",
            "review_id",
            "transition_reason",
            "activation_authority",
        }
        if set(value) != keys or value.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("MSCP profile lifecycle state has an unsupported schema")
        candidate = value.get("candidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("MSCP profile lifecycle candidate MUST be an object")
        activation_authority = value.get("activation_authority")
        if activation_authority is not False:
            raise ValueError("MSCP profile lifecycle activation_authority MUST be false")
        return cls(
            candidate=MscpCandidateKey(
                action_type=_string(candidate, "action_type"),
                effect_metric=_string(candidate, "effect_metric"),
                environment=_string(candidate, "environment"),
                observer_version=_string(candidate, "observer_version"),
            ),
            mode=MscpProfileMode(_string(value, "mode")),
            revision=_integer(value, "revision"),
            updated_at=_instant(value, "updated_at"),
            readiness_digest=_optional_string(value, "readiness_digest"),
            review_id=_optional_string(value, "review_id"),
            transition_reason=_string(value, "transition_reason"),
        )


class StateStoreMscpProfileLifecycle:
    """Persist reviewed profile state with atomic audit-backed transitions."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def register(
        self,
        candidate: MscpCandidateKey,
        *,
        at: datetime,
    ) -> MscpProfileLifecycleRecord:
        """Create the default shadow state or return its current replay."""

        _require_aware("at", at)
        record = MscpProfileLifecycleRecord(
            candidate=candidate,
            mode=MscpProfileMode.SHADOW,
            revision=1,
            updated_at=at,
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            _state_key(candidate),
            record.to_mapping(),
            _audit("registered", record),
        )
        return record if created else await self.get(candidate)

    async def get(self, candidate: MscpCandidateKey) -> MscpProfileLifecycleRecord:
        """Load one candidate state."""

        value = await self._state_store.read_state(_state_key(candidate))
        if value is None:
            raise KeyError(candidate)
        record = MscpProfileLifecycleRecord.from_mapping(value)
        if record.candidate != candidate:
            raise ValueError("MSCP profile lifecycle candidate identity mismatched")
        return record

    async def promote(
        self,
        candidate: MscpCandidateKey,
        *,
        expected_revision: int,
        readiness: MscpReadinessReport,
        review: IndependentProfileReview,
        at: datetime,
    ) -> MscpProfileLifecycleRecord:
        """Record reviewed gating state without activating any runtime path."""

        _require_aware("at", at)
        digest = readiness_digest(readiness)
        if (
            readiness.candidate != candidate
            or not readiness.ready_for_review
            or readiness.promotion_authority
        ):
            raise MscpProfileLifecycleConflictError(
                "candidate readiness is not eligible for review"
            )
        if (
            review.candidate != candidate
            or review.readiness_digest != digest
            or not review.approved
            or review.reviewed_at > at
        ):
            raise MscpProfileLifecycleConflictError("independent review does not match readiness")
        current = await self.get(candidate)
        if current.revision != expected_revision:
            raise MscpProfileLifecycleConflictError("MSCP profile lifecycle revision is stale")
        if (
            current.mode is MscpProfileMode.GATING
            and current.readiness_digest == digest
            and current.review_id == review.review_id
        ):
            return current
        updated = MscpProfileLifecycleRecord(
            candidate=candidate,
            mode=MscpProfileMode.GATING,
            revision=current.revision + 1,
            updated_at=at,
            readiness_digest=digest,
            review_id=review.review_id,
            transition_reason="independent_review_approved",
        )
        return await self._compare_and_set(current, updated, event="promoted")

    async def demote(
        self,
        candidate: MscpCandidateKey,
        *,
        expected_revision: int,
        reason: str,
        at: datetime,
    ) -> MscpProfileLifecycleRecord:
        """Immediately return a candidate to shadow with an audited reason."""

        _require_aware("at", at)
        if not reason.strip() or len(reason) > 256:
            raise ValueError("demotion reason MUST be bounded non-empty text")
        current = await self.get(candidate)
        if current.revision != expected_revision:
            raise MscpProfileLifecycleConflictError("MSCP profile lifecycle revision is stale")
        updated = MscpProfileLifecycleRecord(
            candidate=candidate,
            mode=MscpProfileMode.SHADOW,
            revision=current.revision + 1,
            updated_at=at,
            readiness_digest=current.readiness_digest,
            review_id=current.review_id,
            transition_reason=reason,
        )
        return await self._compare_and_set(current, updated, event="demoted")

    async def _compare_and_set(
        self,
        current: MscpProfileLifecycleRecord,
        updated: MscpProfileLifecycleRecord,
        *,
        event: str,
    ) -> MscpProfileLifecycleRecord:
        applied = await self._state_store.compare_and_set_state_with_audit(
            _state_key(current.candidate),
            updated.to_mapping(),
            expected_revision=current.revision,
            audit_entry=_audit(event, updated),
        )
        if not applied:
            raise MscpProfileLifecycleConflictError("MSCP profile lifecycle changed concurrently")
        return updated


def readiness_digest(report: MscpReadinessReport) -> str:
    """Return a stable digest for one exact readiness report."""

    encoded = json.dumps(
        asdict(report),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _state_key(candidate: MscpCandidateKey) -> str:
    encoded = json.dumps(asdict(candidate), sort_keys=True, separators=(",", ":")).encode()
    return _STATE_PREFIX + hashlib.sha256(encoded).hexdigest()


def _audit(event: str, record: MscpProfileLifecycleRecord) -> dict[str, object]:
    return {
        "kind": f"mscp.profile_lifecycle.{event}",
        "candidate_digest": _state_key(record.candidate).removeprefix(_STATE_PREFIX),
        "mode": record.mode.value,
        "revision": record.revision,
        "readiness_digest": record.readiness_digest,
        "review_id": record.review_id,
        "transition_reason": record.transition_reason,
        "activation_authority": False,
    }


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"MSCP profile lifecycle {key} MUST be non-empty text")
    return item


def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise ValueError(f"MSCP profile lifecycle {key} MUST be text or null")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"MSCP profile lifecycle {key} MUST be an integer")
    return item


def _instant(value: Mapping[str, Any], key: str) -> datetime:
    parsed = datetime.fromisoformat(_string(value, key).replace("Z", "+00:00"))
    _require_aware(key, parsed)
    return parsed


__all__ = [
    "IndependentProfileReview",
    "MscpProfileLifecycleConflictError",
    "MscpProfileLifecycleRecord",
    "MscpProfileMode",
    "StateStoreMscpProfileLifecycle",
    "readiness_digest",
]
