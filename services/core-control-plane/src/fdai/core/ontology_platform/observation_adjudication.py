"""Deterministic adjudication of repeated authoritative observations of one target.

FDAI-CONST-002 requires conflicting authoritative sources to remain an explicit conflict
that lowers autonomy, and forbids resolving the disagreement by averaging, by preferring
the most recent report, or by weighting one source higher than another. This module is the
adjudication half of that contract: it decides *whether* independently reported claims about
the same target agree, and names the exact disagreements. Consumers of
``StateFactMetadata.conflicts`` already own the demotion half.

The scope covers repeated observations inside one promoted inventory generation and a
provider projection compared with independent telemetry. It is pure, provider-neutral,
and never selects a winning value.

An empty conflict tuple means the compared claims agreed. It never means the target was
independently corroborated, and it never proves absence of a conflict that no source
reported.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

#: Bounded conflict evidence. A wider disagreement is truncated to a stable marker so a
#: hostile or malfunctioning source cannot grow the projected metadata without bound.
MAX_OBSERVATION_CONFLICTS = 32
_MAX_CONFLICT_KEY_CHARS = 96

CONFLICT_PROPERTY_PREFIX = "observed_property_conflict"
CONFLICT_TRUNCATED = "observed_property_conflict_truncated"
CONFLICT_PROVIDER_REF = "observed_provider_ref_conflict"


class ObservationIdentityConflictError(ValueError):
    """Two observations of one neutral identity disagree on the target's type.

    This is an identity-level contradiction rather than a value disagreement: the
    projection cannot type the object's endpoints, so it fails closed instead of
    publishing a contested type.
    """


class CrossSourceStateStatus(StrEnum):
    """Outcome of comparing projected provider state with telemetry."""

    AGREED = "agreed"
    TELEMETRY_MISSING = "telemetry_missing"
    PROJECTION_STALE = "projection_stale"
    TELEMETRY_STALE = "telemetry_stale"
    CONFLICTING = "conflicting"
    CENSORED = "censored"


class CrossSourceReadConfidence(StrEnum):
    """Bounded read confidence that never carries action authority."""

    CORROBORATED = "corroborated"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class StateEvidenceSnapshot:
    """One scoped state value with its original authority and provenance."""

    target_id: str
    scope_ref: str
    state: Mapping[str, Any]
    metadata: StateFactMetadata
    censoring_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("target_id", self.target_id),
            ("scope_ref", self.scope_ref),
        ):
            if not value.strip() or len(value) > 512:
                raise ValueError(f"StateEvidenceSnapshot.{field_name} MUST be bounded text")
        if self.metadata.lane is not StateFactLane.OBSERVED:
            raise ValueError("cross-source state evidence MUST use the observed lane")
        canonical_censoring = tuple(sorted(set(self.censoring_refs)))
        if (
            canonical_censoring != self.censoring_refs
            or len(canonical_censoring) > 64
            or any(not item.strip() or len(item) > 512 for item in canonical_censoring)
        ):
            raise ValueError("censoring_refs MUST be sorted, unique, and bounded")
        canonical_state = _canonical_state_mapping(self.state)
        object.__setattr__(self, "state", canonical_state)


@dataclass(frozen=True, slots=True)
class CrossSourceStateAdjudication:
    """Authority-neutral comparison retaining both source evidence records."""

    status: CrossSourceStateStatus
    read_confidence: CrossSourceReadConfidence
    projection: StateEvidenceSnapshot
    telemetry: StateEvidenceSnapshot | None
    projection_fresh: bool
    telemetry_fresh: bool | None
    agreed_state: Mapping[str, Any]
    conflicting_fields: tuple[str, ...]
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority or self.mutation_authority:
            raise ValueError("cross-source state adjudication MUST NOT grant authority")


@dataclass(frozen=True, slots=True)
class ObservedClaim:
    """One authoritative observation of a single target inside one generation."""

    type: str
    properties: Mapping[str, Any]
    provider_ref: str | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ObservationVerdict:
    """Adjudicated agreement over repeated observations of one target.

    ``agreed_properties`` holds only the property keys every claim reported with an
    identical value. A contested key is absent, so no consumer can read a contested
    value. ``observed_at`` is the earliest reported observation time, which is the
    conservative choice for freshness; it never selects which claim's values win.
    """

    type: str
    agreed_properties: Mapping[str, Any]
    observed_at: datetime | None
    conflicts: tuple[str, ...]

    @property
    def contested(self) -> bool:
        return bool(self.conflicts)


def adjudicate_observations(claims: Sequence[ObservedClaim]) -> ObservationVerdict:
    """Return the agreed content and the explicit conflicts across repeated claims.

    Raises:
        ValueError: ``claims`` is empty.
        ObservationIdentityConflictError: the claims disagree on the observed type.
    """

    if not claims:
        raise ValueError("observation adjudication requires at least one claim")
    types = {claim.type.strip() for claim in claims}
    if len(types) != 1:
        raise ObservationIdentityConflictError(
            "observed target type disagrees across observations in one generation"
        )
    observed_type = types.pop()
    observed_at = _earliest(claim.observed_at for claim in claims)

    if len(claims) == 1:
        return ObservationVerdict(
            type=observed_type,
            agreed_properties=dict(claims[0].properties),
            observed_at=observed_at,
            conflicts=(),
        )

    conflicts: set[str] = set()
    provider_refs = {claim.provider_ref for claim in claims}
    if len(provider_refs) != 1:
        conflicts.add(CONFLICT_PROVIDER_REF)

    agreed: dict[str, Any] = {}
    for key in sorted({str(key) for claim in claims for key in claim.properties}):
        encoded = {_canonical(claim.properties.get(key, _ABSENT)) for claim in claims}
        if len(encoded) == 1:
            agreed[key] = claims[0].properties[key]
            continue
        conflicts.add(f"{CONFLICT_PROPERTY_PREFIX}:{_bounded_key(key)}")

    return ObservationVerdict(
        type=observed_type,
        agreed_properties=agreed,
        observed_at=observed_at,
        conflicts=_bounded_conflicts(conflicts),
    )


def adjudicate_projected_state(
    *,
    projection: StateEvidenceSnapshot,
    telemetry: StateEvidenceSnapshot | None,
    evaluated_at: datetime,
) -> CrossSourceStateAdjudication:
    """Compare one provider projection with independent telemetry evidence."""

    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at MUST be timezone-aware")
    if projection.metadata.authority is not StateFactAuthority.PROVIDER:
        raise ValueError("projected state MUST carry provider authority")
    projection_fresh = _is_fresh(projection.metadata, evaluated_at)
    if telemetry is None:
        return _cross_source_result(
            status=CrossSourceStateStatus.TELEMETRY_MISSING,
            confidence=CrossSourceReadConfidence.DEGRADED,
            projection=projection,
            telemetry=None,
            projection_fresh=projection_fresh,
            telemetry_fresh=None,
            agreed_state=projection.state if projection_fresh else {},
        )
    if telemetry.metadata.authority is not StateFactAuthority.TELEMETRY:
        raise ValueError("telemetry state MUST carry telemetry authority")

    telemetry_fresh = _is_fresh(telemetry.metadata, evaluated_at)
    identity_conflicts = _identity_conflicts(projection, telemetry)
    evidence_conflicts = tuple(
        sorted(
            {
                *(f"projection:{item}" for item in projection.metadata.conflicts),
                *(f"telemetry:{item}" for item in telemetry.metadata.conflicts),
            }
        )
    )
    if projection.censoring_refs or telemetry.censoring_refs:
        return _cross_source_result(
            status=CrossSourceStateStatus.CENSORED,
            confidence=CrossSourceReadConfidence.UNAVAILABLE,
            projection=projection,
            telemetry=telemetry,
            projection_fresh=projection_fresh,
            telemetry_fresh=telemetry_fresh,
        )
    if not projection_fresh:
        return _cross_source_result(
            status=CrossSourceStateStatus.PROJECTION_STALE,
            confidence=CrossSourceReadConfidence.DEGRADED,
            projection=projection,
            telemetry=telemetry,
            projection_fresh=False,
            telemetry_fresh=telemetry_fresh,
        )
    if not telemetry_fresh:
        return _cross_source_result(
            status=CrossSourceStateStatus.TELEMETRY_STALE,
            confidence=CrossSourceReadConfidence.DEGRADED,
            projection=projection,
            telemetry=telemetry,
            projection_fresh=True,
            telemetry_fresh=False,
            agreed_state=projection.state,
        )

    agreed, value_conflicts = _compare_state(projection.state, telemetry.state)
    conflicts = tuple(sorted({*identity_conflicts, *evidence_conflicts, *value_conflicts}))
    if conflicts:
        return _cross_source_result(
            status=CrossSourceStateStatus.CONFLICTING,
            confidence=CrossSourceReadConfidence.DEGRADED,
            projection=projection,
            telemetry=telemetry,
            projection_fresh=True,
            telemetry_fresh=True,
            agreed_state={} if identity_conflicts else agreed,
            conflicting_fields=conflicts,
        )
    return _cross_source_result(
        status=CrossSourceStateStatus.AGREED,
        confidence=CrossSourceReadConfidence.CORROBORATED,
        projection=projection,
        telemetry=telemetry,
        projection_fresh=True,
        telemetry_fresh=True,
        agreed_state=agreed,
    )


def _cross_source_result(
    *,
    status: CrossSourceStateStatus,
    confidence: CrossSourceReadConfidence,
    projection: StateEvidenceSnapshot,
    telemetry: StateEvidenceSnapshot | None,
    projection_fresh: bool,
    telemetry_fresh: bool | None,
    agreed_state: Mapping[str, Any] | None = None,
    conflicting_fields: tuple[str, ...] = (),
) -> CrossSourceStateAdjudication:
    return CrossSourceStateAdjudication(
        status=status,
        read_confidence=confidence,
        projection=projection,
        telemetry=telemetry,
        projection_fresh=projection_fresh,
        telemetry_fresh=telemetry_fresh,
        agreed_state=dict(agreed_state or {}),
        conflicting_fields=conflicting_fields,
    )


def _is_fresh(metadata: StateFactMetadata, evaluated_at: datetime) -> bool:
    evaluated = evaluated_at.astimezone(UTC)
    cutoff = metadata.evidence_cutoff.astimezone(UTC)
    recorded = metadata.recorded_at.astimezone(UTC)
    return (
        cutoff <= evaluated
        and recorded <= evaluated
        and evaluated <= cutoff + timedelta(seconds=metadata.freshness_ceiling_seconds)
    )


def _identity_conflicts(
    projection: StateEvidenceSnapshot,
    telemetry: StateEvidenceSnapshot,
) -> tuple[str, ...]:
    conflicts: list[str] = []
    if projection.target_id != telemetry.target_id:
        conflicts.append("target_id")
    if projection.scope_ref != telemetry.scope_ref:
        conflicts.append("scope_ref")
    return tuple(conflicts)


def _compare_state(
    projection: Mapping[str, Any],
    telemetry: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    agreed: dict[str, Any] = {}
    conflicts: list[str] = []
    for key in sorted(set(projection) | set(telemetry)):
        projected = projection.get(key, _ABSENT)
        observed = telemetry.get(key, _ABSENT)
        if _canonical(projected) == _canonical(observed):
            agreed[key] = projection[key]
        else:
            conflicts.append(key)
    return agreed, tuple(conflicts)


def _canonical_state_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError("StateEvidenceSnapshot.state keys MUST be non-empty strings")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("StateEvidenceSnapshot.state MUST contain JSON values") from exc
    if not isinstance(decoded, dict):
        raise ValueError("StateEvidenceSnapshot.state MUST be a mapping")
    return decoded


_ABSENT = object()


def _canonical(value: Any) -> str:
    """Encode one reported value so equality is exact and order-independent."""

    if value is _ABSENT:
        return "\u0000absent"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)


def _bounded_key(key: str) -> str:
    if len(key) <= _MAX_CONFLICT_KEY_CHARS:
        return key
    return key[:_MAX_CONFLICT_KEY_CHARS]


def _bounded_conflicts(conflicts: set[str]) -> tuple[str, ...]:
    ordered = sorted(conflicts)
    if len(ordered) <= MAX_OBSERVATION_CONFLICTS:
        return tuple(ordered)
    return (*ordered[: MAX_OBSERVATION_CONFLICTS - 1], CONFLICT_TRUNCATED)


def _earliest(values: Iterable[datetime | None]) -> datetime | None:
    aware = [value.astimezone(UTC) for value in values if value is not None]
    return min(aware) if aware else None


__all__ = [
    "CONFLICT_PROPERTY_PREFIX",
    "CONFLICT_PROVIDER_REF",
    "CONFLICT_TRUNCATED",
    "CrossSourceReadConfidence",
    "CrossSourceStateAdjudication",
    "CrossSourceStateStatus",
    "MAX_OBSERVATION_CONFLICTS",
    "ObservationIdentityConflictError",
    "ObservationVerdict",
    "ObservedClaim",
    "StateEvidenceSnapshot",
    "adjudicate_observations",
    "adjudicate_projected_state",
]
