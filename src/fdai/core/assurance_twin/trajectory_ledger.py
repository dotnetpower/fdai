"""Durable predicted-trajectory episodes and independent outcome closure."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.assurance_twin.state_trajectory import (
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
    TrajectoryOutcome,
    TrajectoryOutcomeStatus,
    close_trajectory_outcome,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "dynamic-trajectory-episode"
_MAX_MODEL_REFS = 256


class TrajectoryEpisodeConflictError(RuntimeError):
    """Raised when replay changes an already recorded episode identity."""


@dataclass(frozen=True, slots=True)
class TrajectoryClosure:
    predicted: OperationalStateTrajectory
    observed: OperationalStateTrajectory
    outcome: TrajectoryOutcome
    challenger_model_refs: tuple[str, ...]
    closed: bool
    duplicate: bool


class StateStoreTrajectoryEpisodeLedger:
    """Open and close trajectory episodes with StateStore atomic writes."""

    def __init__(self, store: StateStore, *, max_retries: int = 3) -> None:
        if max_retries < 1:
            raise ValueError("trajectory ledger max_retries MUST be >= 1")
        self._store = store
        self._max_retries = max_retries

    async def record_prediction(
        self,
        predicted: OperationalStateTrajectory,
        *,
        challenger_model_refs: tuple[str, ...],
        recorded_by: str,
        recorded_at: datetime,
    ) -> bool:
        if predicted.kind is not TrajectoryKind.PREDICTED:
            raise ValueError("trajectory episode prediction MUST use predicted kind")
        _validate_model_refs(challenger_model_refs)
        _aware(recorded_at, "trajectory episode recorded_at")
        if not recorded_by.strip():
            raise ValueError("trajectory episode recorded_by MUST be non-empty")
        value = {
            "revision": 1,
            "status": "open",
            "prediction_digest": predicted.digest,
            "predicted": _serialize_trajectory(predicted),
            "challenger_model_refs": list(challenger_model_refs),
            "recorded_at": recorded_at.isoformat(),
        }
        created = await self._store.write_state_with_audit_if_absent(
            _state_key(predicted.digest),
            value,
            {
                "actor": recorded_by,
                "producer_principal": recorded_by,
                "action_kind": "dynamic.trajectory_episode.opened",
                "mode": "shadow",
                "prediction_digest": predicted.digest,
                "challenger_model_refs": list(challenger_model_refs),
                "recorded_at": recorded_at.isoformat(),
            },
        )
        if created:
            return True
        existing = await self._store.read_state(_state_key(predicted.digest))
        if existing is None or not _same_prediction(existing, predicted, challenger_model_refs):
            raise TrajectoryEpisodeConflictError("trajectory prediction identity conflict")
        return False

    async def close(
        self,
        *,
        prediction_digest: str,
        observed: OperationalStateTrajectory,
        recorded_at: datetime,
        absolute_tolerance: float = 0.0,
        relative_tolerance: float = 0.0,
    ) -> TrajectoryClosure:
        _aware(recorded_at, "trajectory closure recorded_at")
        if recorded_at < observed.horizon_end:
            raise ValueError("trajectory closure MUST follow the observation horizon")
        key = _state_key(prediction_digest)
        for _ in range(self._max_retries):
            raw = await self._store.read_state(key)
            if raw is None:
                raise KeyError("trajectory prediction episode was not found")
            predicted = _deserialize_trajectory(_mapping(raw, "predicted"))
            if predicted.digest != prediction_digest:
                raise TrajectoryEpisodeConflictError(
                    "stored trajectory prediction identity mismatch"
                )
            challenger_refs = _text_tuple(raw, "challenger_model_refs")
            if raw.get("status") == "closed":
                stored_observed = _deserialize_trajectory(_mapping(raw, "observed"))
                if stored_observed.digest != observed.digest:
                    raise TrajectoryEpisodeConflictError("trajectory closure observation conflict")
                return TrajectoryClosure(
                    predicted=predicted,
                    observed=stored_observed,
                    outcome=_deserialize_outcome(_mapping(raw, "outcome")),
                    challenger_model_refs=challenger_refs,
                    closed=True,
                    duplicate=True,
                )
            outcome = close_trajectory_outcome(
                predicted,
                observed,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
            if not outcome.challenger_eligible:
                await self._store.append_audit_entry(
                    {
                        "actor": "Norns",
                        "producer_principal": "Norns",
                        "action_kind": "dynamic.trajectory_outcome.rejected",
                        "mode": "shadow",
                        "prediction_digest": prediction_digest,
                        "observation_digest": observed.digest,
                        "outcome_status": outcome.status.value,
                        "reason": outcome.reason,
                        "recorded_at": recorded_at.isoformat(),
                    }
                )
                return TrajectoryClosure(
                    predicted=predicted,
                    observed=observed,
                    outcome=outcome,
                    challenger_model_refs=challenger_refs,
                    closed=False,
                    duplicate=False,
                )
            changed = {
                **dict(raw),
                "revision": int(raw.get("revision", 1)) + 1,
                "status": "closed",
                "observed": _serialize_trajectory(observed),
                "outcome": _serialize_outcome(outcome),
                "closed_at": recorded_at.isoformat(),
            }
            accepted = await self._store.compare_and_set_state_with_audit(
                key,
                changed,
                expected_revision=int(raw.get("revision", 1)),
                audit_entry={
                    "actor": "Norns",
                    "producer_principal": "Norns",
                    "action_kind": "dynamic.trajectory_outcome.closed",
                    "mode": "shadow",
                    "prediction_digest": prediction_digest,
                    "observation_digest": observed.digest,
                    "outcome_status": outcome.status.value,
                    "reason": outcome.reason,
                    "recorded_at": recorded_at.isoformat(),
                },
            )
            if accepted:
                return TrajectoryClosure(
                    predicted=predicted,
                    observed=observed,
                    outcome=outcome,
                    challenger_model_refs=challenger_refs,
                    closed=True,
                    duplicate=False,
                )
        raise TrajectoryEpisodeConflictError("trajectory closure revision conflict")


def _state_key(prediction_digest: str) -> str:
    if len(prediction_digest) != 64 or any(
        character not in "0123456789abcdef" for character in prediction_digest
    ):
        raise ValueError("trajectory prediction digest MUST be SHA-256")
    return f"{_PREFIX}:{prediction_digest}"


def _validate_model_refs(values: tuple[str, ...]) -> None:
    if (
        not values
        or len(values) > _MAX_MODEL_REFS
        or values != tuple(sorted(set(values)))
        or any(not value.strip() or len(value) > 512 for value in values)
    ):
        raise ValueError("trajectory challenger model refs MUST be sorted, unique, and bounded")


def _same_prediction(
    raw: Mapping[str, Any],
    predicted: OperationalStateTrajectory,
    challenger_model_refs: tuple[str, ...],
) -> bool:
    return (
        raw.get("prediction_digest") == predicted.digest
        and _deserialize_trajectory(_mapping(raw, "predicted")) == predicted
        and _text_tuple(raw, "challenger_model_refs") == challenger_model_refs
    )


def _serialize_trajectory(trajectory: OperationalStateTrajectory) -> dict[str, object]:
    return {
        "kind": trajectory.kind.value,
        "ontology_release": trajectory.ontology_release,
        "graph_revision": trajectory.graph_revision,
        "inventory_generation": trajectory.inventory_generation,
        "base_snapshot_id": trajectory.base_snapshot_id,
        "evidence_cutoff": trajectory.evidence_cutoff.isoformat(),
        "horizon_end": trajectory.horizon_end.isoformat(),
        "slices": [
            {
                "object_ref": item.object_ref,
                "object_type": item.object_type,
                "metric": item.metric,
                "value": item.value,
                "effective_at": item.effective_at.isoformat(),
                "evidence_refs": list(item.evidence_refs),
                "model_ref": item.model_ref,
                "independent_observer": item.independent_observer,
            }
            for item in trajectory.slices
        ],
        "intervention_refs": list(trajectory.intervention_refs),
        "censoring_refs": list(trajectory.censoring_refs),
        "source_watermarks": list(trajectory.source_watermarks),
        "complete": trajectory.complete,
        "truncated": trajectory.truncated,
        "truncation_reasons": list(trajectory.truncation_reasons),
        "schema_version": trajectory.schema_version,
    }


def _deserialize_trajectory(raw: Mapping[str, Any]) -> OperationalStateTrajectory:
    slices_raw = raw.get("slices")
    if not isinstance(slices_raw, list):
        raise ValueError("stored trajectory slices MUST be a list")
    slices = tuple(
        StateSlice(
            object_ref=_text(item, "object_ref"),
            object_type=_text(item, "object_type"),
            metric=_text(item, "metric"),
            value=float(item["value"]),
            effective_at=_timestamp(item, "effective_at"),
            evidence_refs=_text_tuple(item, "evidence_refs"),
            model_ref=_optional_text(item, "model_ref"),
            independent_observer=bool(item.get("independent_observer", False)),
        )
        for item in (_mapping_value(value, "trajectory slice") for value in slices_raw)
    )
    return OperationalStateTrajectory(
        kind=TrajectoryKind(_text(raw, "kind")),
        ontology_release=_text(raw, "ontology_release"),
        graph_revision=_text(raw, "graph_revision"),
        inventory_generation=_text(raw, "inventory_generation"),
        base_snapshot_id=_text(raw, "base_snapshot_id"),
        evidence_cutoff=_timestamp(raw, "evidence_cutoff"),
        horizon_end=_timestamp(raw, "horizon_end"),
        slices=slices,
        intervention_refs=_text_tuple(raw, "intervention_refs"),
        censoring_refs=_text_tuple(raw, "censoring_refs"),
        source_watermarks=_text_tuple(raw, "source_watermarks"),
        complete=bool(raw.get("complete", False)),
        truncated=bool(raw.get("truncated", False)),
        truncation_reasons=_text_tuple(raw, "truncation_reasons"),
        schema_version=_text(raw, "schema_version"),
    )


def _serialize_outcome(outcome: TrajectoryOutcome) -> dict[str, object]:
    return {
        "prediction_digest": outcome.prediction_digest,
        "observation_digest": outcome.observation_digest,
        "status": outcome.status.value,
        "compared_slices": outcome.compared_slices,
        "mismatched_keys": [
            [object_ref, metric, effective_at.isoformat()]
            for object_ref, metric, effective_at in outcome.mismatched_keys
        ],
        "evidence_refs": list(outcome.evidence_refs),
        "reason": outcome.reason,
    }


def _deserialize_outcome(raw: Mapping[str, Any]) -> TrajectoryOutcome:
    keys_raw = raw.get("mismatched_keys")
    if not isinstance(keys_raw, list):
        raise ValueError("stored trajectory mismatched_keys MUST be a list")
    keys: list[tuple[str, str, datetime]] = []
    for value in keys_raw:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("stored trajectory mismatch key MUST contain three values")
        keys.append((str(value[0]), str(value[1]), _parse_timestamp(str(value[2]))))
    return TrajectoryOutcome(
        prediction_digest=_text(raw, "prediction_digest"),
        observation_digest=_text(raw, "observation_digest"),
        status=TrajectoryOutcomeStatus(_text(raw, "status")),
        compared_slices=int(raw["compared_slices"]),
        mismatched_keys=tuple(keys),
        evidence_refs=_text_tuple(raw, "evidence_refs"),
        reason=_text(raw, "reason"),
    )


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping_value(raw.get(key), key)


def _mapping_value(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"stored {name} MUST be an object")
    return value


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored trajectory {key} MUST be non-empty")
    return value


def _optional_text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored trajectory {key} MUST be non-empty when present")
    return value


def _text_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"stored trajectory {key} MUST be a string list")
    return tuple(value)


def _timestamp(raw: Mapping[str, Any], key: str) -> datetime:
    return _parse_timestamp(_text(raw, key))


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _aware(parsed, "stored trajectory timestamp")
    return parsed


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "StateStoreTrajectoryEpisodeLedger",
    "TrajectoryClosure",
    "TrajectoryEpisodeConflictError",
]
