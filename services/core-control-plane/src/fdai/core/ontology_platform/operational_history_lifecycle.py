"""Deterministic lifecycle contracts for bounded operational observation history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

_MAX_TEXT = 512
_MAX_REFS = 256


class ObservationPartitionKind(StrEnum):
    """Whether a partition carries first-seen history or late corrections."""

    BASE = "base"
    CORRECTION = "correction"


class ObservationPartitionState(StrEnum):
    """Monotonic lifecycle state for one time-and-scope partition."""

    OPEN = "open"
    SEALED = "sealed"
    CHECKPOINTED = "checkpointed"
    ARCHIVED = "archived"
    VERIFIED = "verified"
    PURGE_ELIGIBLE = "purge_eligible"
    PURGED = "purged"
    HELD = "held"
    CORRECTION_PENDING = "correction_pending"


class ObservationPinKind(StrEnum):
    """Case or governance reason that prevents partition purge."""

    INCIDENT = "incident"
    INVESTIGATION = "investigation"
    APPROVAL = "approval"
    EXECUTION = "execution"
    ROLLBACK = "rollback"
    LEGAL_HOLD = "legal_hold"
    REPLAY_LEASE = "replay_lease"


@dataclass(frozen=True, slots=True)
class ResourceIncarnation:
    """One immutable lifecycle identity for a provider resource identity."""

    incarnation_id: str
    resource_ref: str
    resource_type: str
    provider_identity: str
    lifecycle_boundary_ref: str
    opened_at: datetime
    closed_at: datetime | None
    opening_observation_id: str
    closing_observation_id: str | None
    digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("resource_ref", self.resource_ref),
            ("resource_type", self.resource_type),
            ("provider_identity", self.provider_identity),
            ("lifecycle_boundary_ref", self.lifecycle_boundary_ref),
            ("opening_observation_id", self.opening_observation_id),
        ):
            _text(name, value)
        _digest(self.incarnation_id, "resource incarnation id")
        _digest(self.opening_observation_id, "opening observation id")
        if self.closing_observation_id is not None:
            _digest(self.closing_observation_id, "closing observation id")
        _aware(self.opened_at, "resource incarnation opened_at")
        if self.closed_at is not None:
            _aware(self.closed_at, "resource incarnation closed_at")
            if self.closed_at < self.opened_at or self.closing_observation_id is None:
                raise ValueError("closed resource incarnation requires a valid closing observation")
        elif self.closing_observation_id is not None:
            raise ValueError("open resource incarnation cannot have a closing observation")
        if self.digest != _sha256(_incarnation_body(self)):
            raise ValueError("resource incarnation digest does not match content")
        if self.incarnation_id != self.digest:
            raise ValueError("resource incarnation id does not match content")

    def close(
        self,
        *,
        closed_at: datetime,
        closing_observation_id: str,
    ) -> ResourceIncarnation:
        """Return an explicitly closed copy without changing its stable identity."""

        if self.closed_at is not None:
            if (
                self.closed_at == closed_at
                and self.closing_observation_id == closing_observation_id
            ):
                return self
            raise ValueError("resource incarnation is already closed")
        _aware(closed_at, "resource incarnation closed_at")
        _digest(closing_observation_id, "closing observation id")
        if closed_at < self.opened_at:
            raise ValueError("resource incarnation cannot close before it opens")
        return replace(
            self,
            closed_at=closed_at,
            closing_observation_id=closing_observation_id,
        )


def build_resource_incarnation(
    *,
    resource_ref: str,
    resource_type: str,
    provider_identity: str,
    lifecycle_boundary_ref: str,
    opened_at: datetime,
    opening_observation_id: str,
) -> ResourceIncarnation:
    """Build one content-addressed incarnation from a verified lifecycle boundary."""

    values = {
        "resource_ref": resource_ref,
        "resource_type": resource_type,
        "provider_identity": provider_identity,
        "lifecycle_boundary_ref": lifecycle_boundary_ref,
        "opened_at": opened_at.astimezone(UTC).isoformat(),
        "opening_observation_id": opening_observation_id,
    }
    digest = _sha256(values)
    return ResourceIncarnation(
        incarnation_id=digest,
        resource_ref=resource_ref,
        resource_type=resource_type,
        provider_identity=provider_identity,
        lifecycle_boundary_ref=lifecycle_boundary_ref,
        opened_at=opened_at,
        closed_at=None,
        opening_observation_id=opening_observation_id,
        closing_observation_id=None,
        digest=digest,
    )


@dataclass(frozen=True, slots=True)
class ObservationPartition:
    """One content-addressed logical time-and-scope partition."""

    partition_id: str
    scope_ref: str
    interval_start: datetime
    interval_end: datetime
    first_watermark: int
    last_watermark: int
    kind: ObservationPartitionKind
    state: ObservationPartitionState
    correction_of: str | None
    retention_policy_digest: str
    created_at: datetime
    digest: str

    def __post_init__(self) -> None:
        _digest(self.partition_id, "observation partition id")
        _text("scope_ref", self.scope_ref)
        _aware(self.interval_start, "observation partition interval_start")
        _aware(self.interval_end, "observation partition interval_end")
        _aware(self.created_at, "observation partition created_at")
        if self.interval_end <= self.interval_start:
            raise ValueError("observation partition interval MUST be positive")
        if self.first_watermark < 1 or self.last_watermark < self.first_watermark:
            raise ValueError("observation partition watermarks MUST be positive and monotonic")
        _digest(self.retention_policy_digest, "retention policy digest")
        if self.kind is ObservationPartitionKind.CORRECTION:
            if self.correction_of is None:
                raise ValueError("correction partition requires its affected partition")
            _digest(self.correction_of, "corrected partition id")
        elif self.correction_of is not None:
            raise ValueError("base partition cannot name a corrected partition")
        if self.digest != _sha256(_partition_body(self)):
            raise ValueError("observation partition digest does not match content")
        if self.partition_id != self.digest:
            raise ValueError("observation partition id does not match content")


def build_observation_partition(
    *,
    scope_ref: str,
    interval_start: datetime,
    interval_end: datetime,
    first_watermark: int,
    last_watermark: int,
    kind: ObservationPartitionKind,
    state: ObservationPartitionState,
    correction_of: str | None,
    retention_policy_digest: str,
    created_at: datetime,
) -> ObservationPartition:
    """Build one immutable partition identity and its initial lifecycle state."""

    body = {
        "scope_ref": scope_ref,
        "interval_start": interval_start.astimezone(UTC).isoformat(),
        "interval_end": interval_end.astimezone(UTC).isoformat(),
        "first_watermark": first_watermark,
        "last_watermark": last_watermark,
        "kind": kind.value,
        "correction_of": correction_of,
        "retention_policy_digest": retention_policy_digest,
        "created_at": created_at.astimezone(UTC).isoformat(),
    }
    digest = _sha256(body)
    return ObservationPartition(
        partition_id=digest,
        scope_ref=scope_ref,
        interval_start=interval_start,
        interval_end=interval_end,
        first_watermark=first_watermark,
        last_watermark=last_watermark,
        kind=kind,
        state=state,
        correction_of=correction_of,
        retention_policy_digest=retention_policy_digest,
        created_at=created_at,
        digest=digest,
    )


_FORWARD_STATES = {
    ObservationPartitionState.OPEN: ObservationPartitionState.SEALED,
    ObservationPartitionState.SEALED: ObservationPartitionState.CHECKPOINTED,
    ObservationPartitionState.CHECKPOINTED: ObservationPartitionState.ARCHIVED,
    ObservationPartitionState.ARCHIVED: ObservationPartitionState.VERIFIED,
    ObservationPartitionState.VERIFIED: ObservationPartitionState.PURGE_ELIGIBLE,
    ObservationPartitionState.PURGE_ELIGIBLE: ObservationPartitionState.PURGED,
}


def advance_partition_state(
    partition: ObservationPartition,
    *,
    target: ObservationPartitionState,
) -> ObservationPartition:
    """Advance one partition without skipping verification gates."""

    if target in {
        ObservationPartitionState.HELD,
        ObservationPartitionState.CORRECTION_PENDING,
    }:
        if partition.state is ObservationPartitionState.PURGED:
            raise ValueError("purged observation partition cannot be blocked")
        return replace(partition, state=target)
    if partition.state in {
        ObservationPartitionState.HELD,
        ObservationPartitionState.CORRECTION_PENDING,
    }:
        if target not in {
            ObservationPartitionState.CHECKPOINTED,
            ObservationPartitionState.VERIFIED,
        }:
            raise ValueError("blocked observation partition requires checkpoint recovery")
        return replace(partition, state=target)
    if _FORWARD_STATES.get(partition.state) is not target:
        raise ValueError("observation partition lifecycle cannot skip or move backward")
    return replace(partition, state=target)


@dataclass(frozen=True, slots=True)
class ObservationCheckpoint:
    """Purge authority binding exact journal and projection coverage."""

    checkpoint_id: str
    partition_id: str
    first_watermark: int
    last_watermark: int
    scope_ref: str
    object_count: int
    relationship_count: int
    property_count: int
    source_digest: str
    schema_digest: str
    ontology_release_digest: str
    projection_digest: str
    projection_watermark: int
    graph_digest: str
    missing_count: int
    quarantined_count: int
    conflicted_count: int
    tombstoned_count: int
    valid: bool
    created_at: datetime
    digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("partition_id", self.partition_id),
            ("source_digest", self.source_digest),
            ("schema_digest", self.schema_digest),
            ("ontology_release_digest", self.ontology_release_digest),
            ("projection_digest", self.projection_digest),
            ("graph_digest", self.graph_digest),
        ):
            _digest(value, name)
        _text("scope_ref", self.scope_ref)
        if self.first_watermark < 1 or self.last_watermark < self.first_watermark:
            raise ValueError("checkpoint watermarks MUST be positive and monotonic")
        if self.projection_watermark < self.last_watermark:
            raise ValueError("checkpoint projection watermark trails its journal coverage")
        counts = (
            self.object_count,
            self.relationship_count,
            self.property_count,
            self.missing_count,
            self.quarantined_count,
            self.conflicted_count,
            self.tombstoned_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("checkpoint counts MUST be non-negative")
        _aware(self.created_at, "checkpoint created_at")
        if self.digest != _sha256(_checkpoint_body(self)):
            raise ValueError("checkpoint digest does not match content")
        if self.checkpoint_id != self.digest:
            raise ValueError("checkpoint id does not match content")


def build_observation_checkpoint(**values: object) -> ObservationCheckpoint:
    """Build one exact content-addressed checkpoint."""

    normalized = {**values, "valid": bool(values.get("valid", True))}
    body = _checkpoint_body_from_values(normalized)
    digest = _sha256(body)
    return ObservationCheckpoint(
        checkpoint_id=digest,
        digest=digest,
        **normalized,  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class ObservationPartitionPin:
    """One append-only placement or release of a partition pin."""

    pin_event_id: str
    pin_id: str
    partition_id: str
    kind: ObservationPinKind
    case_ref: str
    placed_at: datetime
    released_at: datetime | None
    expires_at: datetime | None
    evidence_refs: tuple[str, ...]
    digest: str

    def __post_init__(self) -> None:
        _digest(self.pin_event_id, "partition pin event id")
        _digest(self.pin_id, "partition pin id")
        _digest(self.partition_id, "partition id")
        _text("case_ref", self.case_ref)
        _aware(self.placed_at, "partition pin placed_at")
        if self.kind is ObservationPinKind.LEGAL_HOLD and self.expires_at is not None:
            raise ValueError("legal-hold partition pin cannot expire")
        for value in (self.released_at, self.expires_at):
            if value is not None:
                _aware(value, "partition pin timestamp")
                if value < self.placed_at:
                    raise ValueError("partition pin timestamp precedes placement")
        _refs(self.evidence_refs, required=True)
        if self.digest != _sha256(_pin_body(self)):
            raise ValueError("partition pin digest does not match content")
        if self.pin_event_id != self.digest:
            raise ValueError("partition pin event id does not match content")

    def active_at(self, at: datetime) -> bool:
        """Return whether this pin blocks purge at the supplied cutoff."""

        _aware(at, "partition pin evaluation time")
        return (
            at >= self.placed_at
            and (self.released_at is None or at < self.released_at)
            and (self.expires_at is None or at < self.expires_at)
        )


def build_partition_pin(
    *,
    partition_id: str,
    kind: ObservationPinKind,
    case_ref: str,
    placed_at: datetime,
    released_at: datetime | None,
    expires_at: datetime | None,
    evidence_refs: tuple[str, ...],
) -> ObservationPartitionPin:
    """Build one pin state event with a stable logical pin identity."""

    pin_id = _sha256(
        {
            "partition_id": partition_id,
            "kind": kind.value,
            "case_ref": case_ref,
            "placed_at": placed_at.astimezone(UTC).isoformat(),
        }
    )
    body = {
        "pin_id": pin_id,
        "partition_id": partition_id,
        "kind": kind.value,
        "case_ref": case_ref,
        "placed_at": placed_at.astimezone(UTC).isoformat(),
        "released_at": (
            released_at.astimezone(UTC).isoformat() if released_at is not None else None
        ),
        "expires_at": (expires_at.astimezone(UTC).isoformat() if expires_at is not None else None),
        "evidence_refs": list(evidence_refs),
    }
    digest = _sha256(body)
    return ObservationPartitionPin(
        pin_event_id=digest,
        pin_id=pin_id,
        partition_id=partition_id,
        kind=kind,
        case_ref=case_ref,
        placed_at=placed_at,
        released_at=released_at,
        expires_at=expires_at,
        evidence_refs=evidence_refs,
        digest=digest,
    )


@dataclass(frozen=True, slots=True)
class ObservationCorrectionReceipt:
    """Close one late-correction interval after deterministic replay."""

    receipt_id: str
    correction_partition_id: str
    affected_checkpoint_ids: tuple[str, ...]
    correction_manifest_digest: str
    replay_receipt_digest: str
    resulting_graph_digest: str
    projection_watermark: int
    closed_at: datetime
    complete: bool
    digest: str

    def __post_init__(self) -> None:
        _digest(self.correction_partition_id, "correction partition id")
        _refs(self.affected_checkpoint_ids)
        for value in (
            self.correction_manifest_digest,
            self.replay_receipt_digest,
            self.resulting_graph_digest,
        ):
            _digest(value, "correction digest")
        if self.projection_watermark < 1:
            raise ValueError("correction projection watermark MUST be positive")
        _aware(self.closed_at, "correction closed_at")
        if self.complete != bool(self.replay_receipt_digest and self.resulting_graph_digest):
            raise ValueError("correction completion does not match replay evidence")
        if self.digest != _sha256(_correction_body(self)):
            raise ValueError("correction receipt digest does not match content")
        if self.receipt_id != self.digest:
            raise ValueError("correction receipt id does not match content")


def build_correction_receipt(**values: object) -> ObservationCorrectionReceipt:
    """Build one content-addressed correction closure."""

    normalized = {**values, "complete": True}
    digest = _sha256(_correction_body_from_values(normalized))
    return ObservationCorrectionReceipt(
        receipt_id=digest,
        digest=digest,
        **normalized,  # type: ignore[arg-type]
    )


def active_partition_pins(
    pins: Sequence[ObservationPartitionPin],
    *,
    at: datetime,
) -> tuple[str, ...]:
    """Return stable logical pin ids that block purge."""

    latest: dict[str, ObservationPartitionPin] = {}
    for pin in pins:
        prior = latest.get(pin.pin_id)
        if prior is None or (
            pin.released_at or pin.placed_at,
            pin.pin_event_id,
        ) > (
            prior.released_at or prior.placed_at,
            prior.pin_event_id,
        ):
            latest[pin.pin_id] = pin
    return tuple(sorted(pin.pin_id for pin in latest.values() if pin.active_at(at)))


def partition_purge_reasons(
    *,
    partition: ObservationPartition,
    checkpoint: ObservationCheckpoint | None,
    archive_verified: bool,
    restore_passed: bool,
    retention_permitted: bool,
    pins: Sequence[ObservationPartitionPin],
    evaluated_at: datetime,
) -> tuple[str, ...]:
    """Return every reason source deletion remains blocked."""

    reasons: list[str] = []
    if partition.state is not ObservationPartitionState.PURGE_ELIGIBLE:
        reasons.append("partition_not_purge_eligible")
    if checkpoint is None or not checkpoint.valid:
        reasons.append("checkpoint_unavailable")
    elif checkpoint.partition_id != partition.partition_id:
        reasons.append("checkpoint_partition_mismatch")
    if not archive_verified:
        reasons.append("archive_unverified")
    if not restore_passed:
        reasons.append("restore_sample_failed")
    if not retention_permitted:
        reasons.append("retention_hold_active")
    if active_partition_pins(pins, at=evaluated_at):
        reasons.append("partition_pin_active")
    if partition.kind is ObservationPartitionKind.CORRECTION and checkpoint is None:
        reasons.append("correction_unclosed")
    return tuple(sorted(set(reasons)))


def _incarnation_body(value: ResourceIncarnation) -> dict[str, object]:
    return {
        "resource_ref": value.resource_ref,
        "resource_type": value.resource_type,
        "provider_identity": value.provider_identity,
        "lifecycle_boundary_ref": value.lifecycle_boundary_ref,
        "opened_at": value.opened_at.astimezone(UTC).isoformat(),
        "opening_observation_id": value.opening_observation_id,
    }


def _partition_body(value: ObservationPartition) -> dict[str, object]:
    return {
        "scope_ref": value.scope_ref,
        "interval_start": value.interval_start.astimezone(UTC).isoformat(),
        "interval_end": value.interval_end.astimezone(UTC).isoformat(),
        "first_watermark": value.first_watermark,
        "last_watermark": value.last_watermark,
        "kind": value.kind.value,
        "correction_of": value.correction_of,
        "retention_policy_digest": value.retention_policy_digest,
        "created_at": value.created_at.astimezone(UTC).isoformat(),
    }


def _checkpoint_body(value: ObservationCheckpoint) -> dict[str, object]:
    return _checkpoint_body_from_values(
        {
            name: getattr(value, name)
            for name in ObservationCheckpoint.__dataclass_fields__
            if name not in {"checkpoint_id", "digest"}
        }
    )


def _checkpoint_body_from_values(values: Mapping[str, object]) -> dict[str, object]:
    return {
        key: (value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value)
        for key, value in values.items()
    }


def _pin_body(value: ObservationPartitionPin) -> dict[str, object]:
    return {
        "pin_id": value.pin_id,
        "partition_id": value.partition_id,
        "kind": value.kind.value,
        "case_ref": value.case_ref,
        "placed_at": value.placed_at.astimezone(UTC).isoformat(),
        "released_at": (
            value.released_at.astimezone(UTC).isoformat() if value.released_at is not None else None
        ),
        "expires_at": (
            value.expires_at.astimezone(UTC).isoformat() if value.expires_at is not None else None
        ),
        "evidence_refs": list(value.evidence_refs),
    }


def _correction_body(value: ObservationCorrectionReceipt) -> dict[str, object]:
    return _correction_body_from_values(
        {
            name: getattr(value, name)
            for name in ObservationCorrectionReceipt.__dataclass_fields__
            if name not in {"receipt_id", "digest"}
        }
    )


def _correction_body_from_values(values: Mapping[str, object]) -> dict[str, object]:
    return {
        key: (
            value.astimezone(UTC).isoformat()
            if isinstance(value, datetime)
            else list(value)
            if isinstance(value, tuple)
            else value
        )
        for key, value in values.items()
    }


def _text(name: str, value: str) -> None:
    if not value or len(value) > _MAX_TEXT:
        raise ValueError(f"{name} MUST be bounded non-empty text")


def _digest(value: str, name: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{name} MUST be a canonical SHA-256 digest")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _refs(values: tuple[str, ...], *, required: bool = False) -> None:
    if required and not values:
        raise ValueError("evidence references MUST NOT be empty")
    if len(values) > _MAX_REFS or values != tuple(sorted(set(values))):
        raise ValueError("evidence references MUST be bounded, sorted, and unique")
    for value in values:
        _text("evidence reference", value)


def _sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ObservationCheckpoint",
    "ObservationCorrectionReceipt",
    "ObservationPartition",
    "ObservationPartitionKind",
    "ObservationPartitionPin",
    "ObservationPartitionState",
    "ObservationPinKind",
    "ResourceIncarnation",
    "active_partition_pins",
    "advance_partition_state",
    "build_correction_receipt",
    "build_observation_checkpoint",
    "build_observation_partition",
    "build_partition_pin",
    "build_resource_incarnation",
    "partition_purge_reasons",
]
