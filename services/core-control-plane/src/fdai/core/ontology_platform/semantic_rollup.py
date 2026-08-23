"""Build typed, coverage-preserving rollups from immutable observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class RollupFactKind(StrEnum):
    """Select one reviewed aggregation family."""

    GAUGE = "gauge"
    COUNTER = "counter"
    CATEGORICAL_STATE = "categorical_state"
    RELATIONSHIP_CHANGE = "relationship_change"
    EVIDENCE_HEALTH = "evidence_health"


class RelationshipChange(StrEnum):
    """Describe one observed relationship transition."""

    ADDED = "added"
    REMOVED = "removed"


class EvidenceHealth(StrEnum):
    """Describe the evidence posture of one observation interval."""

    HEALTHY = "healthy"
    INCOMPLETE = "incomplete"
    CONFLICTING = "conflicting"


_ALLOWED_STATISTICS = {
    RollupFactKind.GAUGE: frozenset({"count", "sum", "minimum", "maximum", "average"}),
    RollupFactKind.COUNTER: frozenset({"count", "sum", "average"}),
    RollupFactKind.CATEGORICAL_STATE: frozenset({"state_counts", "latest"}),
    RollupFactKind.RELATIONSHIP_CHANGE: frozenset({"change_counts"}),
    RollupFactKind.EVIDENCE_HEALTH: frozenset({"health_counts"}),
}


@dataclass(frozen=True, slots=True)
class SemanticRollupPolicy:
    """Declare one semantic fact's window and mergeable statistics."""

    semantic_id: str
    revision: str
    ontology_release_digest: str
    fact_kind: RollupFactKind
    expected_interval_seconds: int
    statistics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.semantic_id or not self.revision:
            raise ValueError("rollup policy identity and revision MUST be non-empty")
        _digest(self.ontology_release_digest, "ontology_release_digest")
        if self.expected_interval_seconds < 1:
            raise ValueError("rollup expected interval MUST be positive")
        if not self.statistics or len(set(self.statistics)) != len(self.statistics):
            raise ValueError("rollup statistics MUST be non-empty and unique")
        unsupported = set(self.statistics) - _ALLOWED_STATISTICS[self.fact_kind]
        if unsupported:
            raise ValueError(f"rollup statistics are unsupported for {self.fact_kind.value}")
        if "average" in self.statistics and not {"count", "sum"}.issubset(self.statistics):
            raise ValueError("rollup average requires count and sum")


@dataclass(frozen=True, slots=True)
class RollupObservation:
    """Retain one authenticated source fact with bitemporal provenance."""

    observation_id: str
    semantic_id: str
    fact_kind: RollupFactKind
    source_id: str
    source_revision: str
    source_partition_digest: str
    generation_ref: str
    ontology_release_digest: str
    interval_start: datetime
    interval_end: datetime
    effective_at: datetime
    event_at: datetime | None
    recorded_at: datetime
    value: Decimal | str | RelationshipChange | EvidenceHealth
    complete: bool = True
    conflict_count: int = 0

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "semantic_id",
            "source_id",
            "source_revision",
            "generation_ref",
        ):
            if not getattr(self, name):
                raise ValueError(f"rollup observation {name} MUST be non-empty")
        _digest(self.source_partition_digest, "source_partition_digest")
        _digest(self.ontology_release_digest, "ontology_release_digest")
        for name in ("interval_start", "interval_end", "effective_at", "recorded_at"):
            _aware(getattr(self, name), name)
        if self.event_at is not None:
            _aware(self.event_at, "event_at")
        if self.interval_end <= self.interval_start:
            raise ValueError("rollup observation interval MUST be positive")
        if self.conflict_count < 0:
            raise ValueError("rollup observation conflict_count MUST NOT be negative")
        if self.fact_kind in {RollupFactKind.GAUGE, RollupFactKind.COUNTER}:
            if not isinstance(self.value, Decimal):
                raise ValueError("numeric rollup observation value MUST be Decimal")
        elif self.fact_kind is RollupFactKind.RELATIONSHIP_CHANGE:
            if not isinstance(self.value, RelationshipChange):
                raise ValueError("relationship rollup observation value is invalid")
        elif self.fact_kind is RollupFactKind.EVIDENCE_HEALTH:
            if not isinstance(self.value, EvidenceHealth):
                raise ValueError("evidence-health rollup observation value is invalid")
        elif not isinstance(self.value, str) or not self.value:
            raise ValueError("categorical rollup observation value MUST be non-empty")


@dataclass(frozen=True, slots=True)
class SemanticRollup:
    """Carry one content-addressed aggregate without erasing coverage gaps."""

    semantic_id: str
    fact_kind: RollupFactKind
    policy_revision: str
    ontology_release_digest: str
    window_start: datetime
    window_end: datetime
    observation_count: int
    source_ids: tuple[str, ...]
    source_revisions: tuple[str, ...]
    source_partition_digests: tuple[str, ...]
    generation_refs: tuple[str, ...]
    effective_time_range: tuple[datetime, datetime] | None
    event_time_range: tuple[datetime, datetime] | None
    event_time_missing: bool
    recorded_time_range: tuple[datetime, datetime] | None
    missing_intervals: tuple[tuple[datetime, datetime], ...]
    observed_zero: bool
    conflict_count: int
    complete: bool
    statistics_json: str
    percentiles_available: bool
    digest: str

    @property
    def source_count(self) -> int:
        """Return the number of distinct authenticated sources."""

        return len(self.source_ids)


def build_semantic_rollup(
    policy: SemanticRollupPolicy,
    observations: tuple[RollupObservation, ...],
    *,
    window_start: datetime,
    window_end: datetime,
) -> SemanticRollup:
    """Aggregate one window and reject mixed or ambiguous provenance."""

    _aware(window_start, "window_start")
    _aware(window_end, "window_end")
    if window_end <= window_start:
        raise ValueError("rollup window MUST be positive")
    grouped: dict[str, list[RollupObservation]] = {}
    for observation in observations:
        if (
            observation.semantic_id != policy.semantic_id
            or observation.fact_kind is not policy.fact_kind
        ):
            raise ValueError("rollup observation does not match its semantic policy")
        if observation.interval_start < window_start or observation.interval_end > window_end:
            raise ValueError("rollup observation MUST be contained by the window")
        grouped.setdefault(observation.observation_id, []).append(observation)
    unique: dict[str, RollupObservation] = {}
    for observation_id, deliveries in grouped.items():
        first = deliveries[0]
        if any(not _same_observed_fact(first, item) for item in deliveries[1:]):
            raise ValueError("rollup observation id collision")
        unique[observation_id] = replace(
            first,
            source_revision=min(item.source_revision for item in deliveries),
            generation_ref=min(item.generation_ref for item in deliveries),
            recorded_at=max(item.recorded_at for item in deliveries),
            complete=all(item.complete for item in deliveries),
            conflict_count=max(item.conflict_count for item in deliveries),
        )
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.event_at or item.effective_at, item.observation_id),
        )
    )
    if any(item.ontology_release_digest != policy.ontology_release_digest for item in ordered):
        raise ValueError("rollup observation ontology release does not match its policy")
    statistics = _statistics(policy, ordered)
    missing = _missing_intervals(
        ordered,
        window_start=window_start,
        window_end=window_end,
        interval_seconds=policy.expected_interval_seconds,
    )
    conflicts = sum(item.conflict_count for item in ordered)
    complete = (
        bool(ordered) and not missing and conflicts == 0 and all(item.complete for item in ordered)
    )
    statistics_json = _canonical_json(statistics)
    source_ids = tuple(sorted({item.source_id for item in ordered}))
    source_revisions = tuple(
        sorted({f"{item.source_id}@{item.source_revision}" for item in observations})
    )
    source_partition_digests = tuple(sorted({item.source_partition_digest for item in ordered}))
    generation_refs = tuple(sorted({item.generation_ref for item in observations}))
    effective_time_range = _time_range(tuple(item.effective_at for item in ordered))
    event_times = tuple(item.event_at for item in ordered if item.event_at is not None)
    event_time_range = _time_range(event_times)
    recorded_time_range = _time_range(tuple(item.recorded_at for item in observations))
    body = {
        "semantic_id": policy.semantic_id,
        "fact_kind": policy.fact_kind.value,
        "policy_revision": policy.revision,
        "ontology_release_digest": policy.ontology_release_digest,
        "window_start": window_start.astimezone(UTC).isoformat(),
        "window_end": window_end.astimezone(UTC).isoformat(),
        "observation_count": len(ordered),
        "source_ids": source_ids,
        "source_revisions": source_revisions,
        "source_partition_digests": source_partition_digests,
        "generation_refs": generation_refs,
        "effective_time_range": _serialized_range(effective_time_range),
        "event_time_range": _serialized_range(event_time_range),
        "event_time_missing": not ordered or len(event_times) != len(ordered),
        "recorded_time_range": _serialized_range(recorded_time_range),
        "missing_intervals": [
            [start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()]
            for start, end in missing
        ],
        "observed_zero": any(item.value == Decimal(0) for item in ordered),
        "conflict_count": conflicts,
        "complete": complete,
        "statistics": statistics,
        "percentiles_available": False,
    }
    return SemanticRollup(
        semantic_id=policy.semantic_id,
        fact_kind=policy.fact_kind,
        policy_revision=policy.revision,
        ontology_release_digest=policy.ontology_release_digest,
        window_start=window_start,
        window_end=window_end,
        observation_count=len(ordered),
        source_ids=source_ids,
        source_revisions=source_revisions,
        source_partition_digests=source_partition_digests,
        generation_refs=generation_refs,
        effective_time_range=effective_time_range,
        event_time_range=event_time_range,
        event_time_missing=not ordered or len(event_times) != len(ordered),
        recorded_time_range=recorded_time_range,
        missing_intervals=missing,
        observed_zero=bool(body["observed_zero"]),
        conflict_count=conflicts,
        complete=complete,
        statistics_json=statistics_json,
        percentiles_available=False,
        digest=_sha256(body),
    )


def _statistics(
    policy: SemanticRollupPolicy,
    observations: tuple[RollupObservation, ...],
) -> dict[str, object]:
    if policy.fact_kind in {RollupFactKind.GAUGE, RollupFactKind.COUNTER}:
        numeric_values = tuple(
            item.value for item in observations if isinstance(item.value, Decimal)
        )
        result: dict[str, object] = {}
        if "count" in policy.statistics:
            result["count"] = len(numeric_values)
        if "sum" in policy.statistics:
            result["sum"] = _decimal(sum(numeric_values, start=Decimal(0)))
        if numeric_values and "minimum" in policy.statistics:
            result["minimum"] = _decimal(min(numeric_values))
        if numeric_values and "maximum" in policy.statistics:
            result["maximum"] = _decimal(max(numeric_values))
        if numeric_values and "average" in policy.statistics:
            result["average"] = _decimal(
                sum(numeric_values, start=Decimal(0)) / len(numeric_values)
            )
        return result
    if policy.fact_kind is RollupFactKind.CATEGORICAL_STATE:
        category_values = tuple(str(item.value) for item in observations)
        counts = {value: category_values.count(value) for value in sorted(set(category_values))}
        return {
            "state_counts": counts,
            "latest": category_values[-1] if category_values else None,
        }
    if policy.fact_kind is RollupFactKind.RELATIONSHIP_CHANGE:
        return {
            "added": sum(item.value is RelationshipChange.ADDED for item in observations),
            "removed": sum(item.value is RelationshipChange.REMOVED for item in observations),
        }
    return {
        value.value: sum(item.value is value for item in observations) for value in EvidenceHealth
    }


def _missing_intervals(
    observations: tuple[RollupObservation, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    interval_seconds: int,
) -> tuple[tuple[datetime, datetime], ...]:
    missing: list[tuple[datetime, datetime]] = []
    cursor = window_start
    step = timedelta(seconds=interval_seconds)
    while cursor < window_end:
        slot_end = min(cursor + step, window_end)
        if not any(
            item.interval_start <= cursor and item.interval_end >= slot_end for item in observations
        ):
            missing.append((cursor, slot_end))
        cursor = slot_end
    return tuple(missing)


def _same_observed_fact(
    first: RollupObservation,
    other: RollupObservation,
) -> bool:
    """Ignore delivery lineage while comparing one provider-observed fact."""

    return (
        replace(
            first,
            source_revision=other.source_revision,
            generation_ref=other.generation_ref,
            recorded_at=other.recorded_at,
            complete=other.complete,
            conflict_count=other.conflict_count,
        )
        == other
    )


def _decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


def _time_range(values: tuple[datetime, ...]) -> tuple[datetime, datetime] | None:
    return (min(values), max(values)) if values else None


def _serialized_range(
    value: tuple[datetime, datetime] | None,
) -> tuple[str, str] | None:
    if value is None:
        return None
    return (
        value[0].astimezone(UTC).isoformat(),
        value[1].astimezone(UTC).isoformat(),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"rollup {name} MUST be a canonical SHA-256 digest")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"rollup {name} MUST be timezone-aware")


__all__ = [
    "EvidenceHealth",
    "RelationshipChange",
    "RollupFactKind",
    "RollupObservation",
    "SemanticRollup",
    "SemanticRollupPolicy",
    "build_semantic_rollup",
]
