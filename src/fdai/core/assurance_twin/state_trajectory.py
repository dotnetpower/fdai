"""Immutable graph-state trajectories and Dynamic outcome closure."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_MAX_SLICES = 4096
_MAX_REFS = 256


class TrajectoryKind(StrEnum):
    PREDICTED = "predicted"
    OBSERVED = "observed"


class InvariantOperator(StrEnum):
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


class InvariantStatus(StrEnum):
    PASSED = "passed"
    VIOLATED = "violated"
    UNSCORABLE = "unscorable"


class TrajectoryOutcomeStatus(StrEnum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    INTERVENTION_CENSORED = "intervention_censored"
    INCOMPLETE = "incomplete"
    UNSCORABLE = "unscorable"


@dataclass(frozen=True, slots=True)
class StateSlice:
    """One normalized object metric at one event-time point."""

    object_ref: str
    object_type: str
    metric: str
    value: float
    effective_at: datetime
    evidence_refs: tuple[str, ...] = ()
    model_ref: str | None = None
    independent_observer: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("object_ref", self.object_ref),
            ("object_type", self.object_type),
            ("metric", self.metric),
        ):
            _bounded_text(name, value)
        _aware("effective_at", self.effective_at)
        if not math.isfinite(self.value):
            raise ValueError("state slice value MUST be finite")
        _bounded_refs("state slice evidence_refs", self.evidence_refs)
        if self.model_ref is not None:
            _bounded_text("model_ref", self.model_ref)

    @property
    def key(self) -> tuple[str, str, datetime]:
        return self.object_ref, self.metric, self.effective_at.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class OperationalStateTrajectory:
    """One replay-stable predicted or independently observed state path."""

    kind: TrajectoryKind
    ontology_release: str
    graph_revision: str
    inventory_generation: str
    base_snapshot_id: str
    evidence_cutoff: datetime
    horizon_end: datetime
    slices: tuple[StateSlice, ...]
    intervention_refs: tuple[str, ...] = ()
    censoring_refs: tuple[str, ...] = ()
    source_watermarks: tuple[str, ...] = ()
    complete: bool = True
    truncated: bool = False
    truncation_reasons: tuple[str, ...] = ()
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.ontology_release) is None:
            raise ValueError("trajectory ontology_release MUST be a SHA-256 digest")
        for name, value in (
            ("graph_revision", self.graph_revision),
            ("inventory_generation", self.inventory_generation),
            ("base_snapshot_id", self.base_snapshot_id),
            ("schema_version", self.schema_version),
        ):
            _bounded_text(name, value)
        _aware("evidence_cutoff", self.evidence_cutoff)
        _aware("horizon_end", self.horizon_end)
        if self.horizon_end < self.evidence_cutoff:
            raise ValueError("trajectory horizon_end MUST NOT precede evidence_cutoff")
        if not self.slices or len(self.slices) > _MAX_SLICES:
            raise ValueError(f"trajectory slices MUST contain 1..{_MAX_SLICES} values")
        keys = tuple(state_slice.key for state_slice in self.slices)
        if len(keys) != len(set(keys)):
            raise ValueError("trajectory slices MUST have unique object, metric, and time keys")
        if keys != tuple(sorted(keys)):
            raise ValueError("trajectory slices MUST use deterministic key order")
        cutoff = self.evidence_cutoff.astimezone(UTC)
        horizon = self.horizon_end.astimezone(UTC)
        if any(not cutoff <= state_slice.key[2] <= horizon for state_slice in self.slices):
            raise ValueError("trajectory slices MUST fall inside the declared horizon")
        if self.kind is TrajectoryKind.PREDICTED and any(
            state_slice.model_ref is None for state_slice in self.slices
        ):
            raise ValueError("predicted trajectory slices MUST name a model_ref")
        if self.kind is TrajectoryKind.OBSERVED and any(
            not state_slice.independent_observer or not state_slice.evidence_refs
            for state_slice in self.slices
        ):
            raise ValueError("observed trajectory slices MUST carry independent observer evidence")
        for name, values in (
            ("intervention_refs", self.intervention_refs),
            ("censoring_refs", self.censoring_refs),
            ("source_watermarks", self.source_watermarks),
            ("truncation_reasons", self.truncation_reasons),
        ):
            _bounded_refs(f"trajectory {name}", values)
        if self.complete and self.truncated:
            raise ValueError("a truncated trajectory cannot be complete")
        if self.truncated != bool(self.truncation_reasons):
            raise ValueError("trajectory truncation MUST include exact reasons")
        if self.censoring_refs and self.kind is not TrajectoryKind.OBSERVED:
            raise ValueError("only observed trajectories may carry censoring_refs")

    @property
    def digest(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "ontology_release": self.ontology_release,
            "graph_revision": self.graph_revision,
            "inventory_generation": self.inventory_generation,
            "base_snapshot_id": self.base_snapshot_id,
            "evidence_cutoff": _timestamp(self.evidence_cutoff),
            "horizon_end": _timestamp(self.horizon_end),
            "slices": [
                {
                    "object_ref": item.object_ref,
                    "object_type": item.object_type,
                    "metric": item.metric,
                    "value": item.value,
                    "effective_at": _timestamp(item.effective_at),
                    "evidence_refs": list(item.evidence_refs),
                    "model_ref": item.model_ref,
                    "independent_observer": item.independent_observer,
                }
                for item in self.slices
            ],
            "intervention_refs": list(self.intervention_refs),
            "censoring_refs": list(self.censoring_refs),
            "source_watermarks": list(self.source_watermarks),
            "complete": self.complete,
            "truncated": self.truncated,
            "truncation_reasons": list(self.truncation_reasons),
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DynamicInvariant:
    invariant_id: str
    metric: str
    operator: InvariantOperator
    threshold: float
    target_ref: str | None = None

    def __post_init__(self) -> None:
        _bounded_text("invariant_id", self.invariant_id)
        _bounded_text("invariant metric", self.metric)
        if self.target_ref is not None:
            _bounded_text("invariant target_ref", self.target_ref)
        if not math.isfinite(self.threshold):
            raise ValueError("invariant threshold MUST be finite")


@dataclass(frozen=True, slots=True)
class InvariantResult:
    invariant_id: str
    status: InvariantStatus
    violating_keys: tuple[tuple[str, str, datetime], ...] = ()
    reason: str = ""


def evaluate_dynamic_invariants(
    trajectory: OperationalStateTrajectory,
    invariants: tuple[DynamicInvariant, ...],
) -> tuple[InvariantResult, ...]:
    """Evaluate every declared bound over all matching trajectory slices."""

    if not invariants or len({item.invariant_id for item in invariants}) != len(invariants):
        raise ValueError("dynamic invariants MUST be non-empty with unique ids")
    results: list[InvariantResult] = []
    for invariant in sorted(invariants, key=lambda item: item.invariant_id):
        matching = tuple(
            item
            for item in trajectory.slices
            if item.metric == invariant.metric
            and (invariant.target_ref is None or item.object_ref == invariant.target_ref)
        )
        if not trajectory.complete or trajectory.truncated or not matching:
            results.append(
                InvariantResult(
                    invariant.invariant_id,
                    InvariantStatus.UNSCORABLE,
                    reason="trajectory_incomplete" if matching else "matching_state_unavailable",
                )
            )
            continue
        violating = tuple(
            item.key for item in matching if not _passes_invariant(item.value, invariant)
        )
        results.append(
            InvariantResult(
                invariant.invariant_id,
                InvariantStatus.VIOLATED if violating else InvariantStatus.PASSED,
                violating_keys=violating,
                reason="invariant_violated" if violating else "invariant_satisfied",
            )
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class TrajectoryOutcome:
    prediction_digest: str
    observation_digest: str
    status: TrajectoryOutcomeStatus
    compared_slices: int
    mismatched_keys: tuple[tuple[str, str, datetime], ...]
    evidence_refs: tuple[str, ...]
    reason: str

    @property
    def challenger_eligible(self) -> bool:
        return self.status in {
            TrajectoryOutcomeStatus.MATCHED,
            TrajectoryOutcomeStatus.MISMATCHED,
        }


def close_trajectory_outcome(
    predicted: OperationalStateTrajectory,
    observed: OperationalStateTrajectory,
    *,
    absolute_tolerance: float = 0.0,
    relative_tolerance: float = 0.0,
) -> TrajectoryOutcome:
    """Compare one prediction with complete independent observations."""

    if predicted.kind is not TrajectoryKind.PREDICTED:
        raise ValueError("predicted trajectory MUST use predicted kind")
    if observed.kind is not TrajectoryKind.OBSERVED:
        raise ValueError("observed trajectory MUST use observed kind")
    if (
        absolute_tolerance < 0.0
        or relative_tolerance < 0.0
        or not all(math.isfinite(value) for value in (absolute_tolerance, relative_tolerance))
    ):
        raise ValueError("trajectory tolerances MUST be finite and non-negative")
    if (
        predicted.ontology_release != observed.ontology_release
        or predicted.graph_revision != observed.graph_revision
        or predicted.inventory_generation != observed.inventory_generation
        or predicted.base_snapshot_id != observed.base_snapshot_id
        or predicted.evidence_cutoff != observed.evidence_cutoff
        or predicted.horizon_end != observed.horizon_end
    ):
        return _outcome(
            predicted,
            observed,
            TrajectoryOutcomeStatus.UNSCORABLE,
            reason="trajectory_identity_mismatch",
        )
    if not predicted.complete or predicted.truncated:
        return _outcome(
            predicted,
            observed,
            TrajectoryOutcomeStatus.UNSCORABLE,
            reason="prediction_incomplete",
        )
    if observed.censoring_refs:
        return _outcome(
            predicted,
            observed,
            TrajectoryOutcomeStatus.INTERVENTION_CENSORED,
            evidence_refs=observed.censoring_refs,
            reason="external_intervention_observed",
        )
    if not observed.complete or observed.truncated:
        return _outcome(
            predicted,
            observed,
            TrajectoryOutcomeStatus.INCOMPLETE,
            evidence_refs=_trajectory_evidence(observed),
            reason="observation_incomplete",
        )
    predicted_by_key = {item.key: item for item in predicted.slices}
    observed_by_key = {item.key: item for item in observed.slices}
    if set(predicted_by_key) != set(observed_by_key):
        return _outcome(
            predicted,
            observed,
            TrajectoryOutcomeStatus.UNSCORABLE,
            evidence_refs=_trajectory_evidence(observed),
            reason="observation_key_mismatch",
        )
    mismatched = tuple(
        key
        for key in sorted(predicted_by_key)
        if abs(predicted_by_key[key].value - observed_by_key[key].value)
        > max(
            absolute_tolerance,
            abs(predicted_by_key[key].value) * relative_tolerance,
        )
    )
    return _outcome(
        predicted,
        observed,
        (TrajectoryOutcomeStatus.MISMATCHED if mismatched else TrajectoryOutcomeStatus.MATCHED),
        compared_slices=len(predicted_by_key),
        mismatched_keys=mismatched,
        evidence_refs=_trajectory_evidence(observed),
        reason="trajectory_mismatch" if mismatched else "trajectory_matched",
    )


def _outcome(
    predicted: OperationalStateTrajectory,
    observed: OperationalStateTrajectory,
    status: TrajectoryOutcomeStatus,
    *,
    compared_slices: int = 0,
    mismatched_keys: tuple[tuple[str, str, datetime], ...] = (),
    evidence_refs: tuple[str, ...] = (),
    reason: str,
) -> TrajectoryOutcome:
    return TrajectoryOutcome(
        prediction_digest=predicted.digest,
        observation_digest=observed.digest,
        status=status,
        compared_slices=compared_slices,
        mismatched_keys=mismatched_keys,
        evidence_refs=evidence_refs,
        reason=reason,
    )


def _trajectory_evidence(trajectory: OperationalStateTrajectory) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            reference
            for state_slice in trajectory.slices
            for reference in state_slice.evidence_refs
        )
    )


def _passes_invariant(value: float, invariant: DynamicInvariant) -> bool:
    if invariant.operator is InvariantOperator.LESS_THAN_OR_EQUAL:
        return value <= invariant.threshold
    return value >= invariant.threshold


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _bounded_text(name: str, value: str) -> None:
    if not value.strip() or len(value) > 512:
        raise ValueError(f"{name} MUST be bounded and non-empty")


def _bounded_refs(name: str, values: tuple[str, ...]) -> None:
    if len(values) > _MAX_REFS or len(values) != len(set(values)):
        raise ValueError(f"{name} MUST be unique and bounded")
    for value in values:
        _bounded_text(name, value)


__all__ = [
    "DynamicInvariant",
    "InvariantOperator",
    "InvariantResult",
    "InvariantStatus",
    "OperationalStateTrajectory",
    "StateSlice",
    "TrajectoryKind",
    "TrajectoryOutcome",
    "TrajectoryOutcomeStatus",
    "close_trajectory_outcome",
    "evaluate_dynamic_invariants",
]
