"""Score frozen predictions against later external observations, never policy effects."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from fdai.core.assurance_twin.feedback_rebuild import latest_feedback_revisions
from fdai.shared.contracts.execution_outcomes import (
    ExecutionLifecycleDisposition,
    execution_lifecycle_disposition,
)
from fdai.shared.contracts.models import ResponseOutcome


@dataclass(frozen=True, slots=True)
class PrequentialEvaluation:
    records: int
    independent_episodes: int
    scored_episodes: int
    held_episodes: int
    mean_absolute_error: float | None
    interval_coverage: float | None
    mean_interval_width: float | None
    source_kind: str
    policy_effect_measured: bool = field(default=False, init=False)
    execution_authority: bool = field(default=False, init=False)
    promotion_authority: bool = field(default=False, init=False)


def evaluate_frozen_predictions(
    outcomes: tuple[ResponseOutcome, ...],
    *,
    as_of: datetime,
    training_independence_keys: frozenset[str],
    source_kind: str,
) -> PrequentialEvaluation:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("prediction evaluation as_of MUST be timezone-aware")
    if source_kind not in {"synthetic", "simulation", "historical", "live_observation"}:
        raise ValueError("prediction evaluation source classification is invalid")
    latest = latest_feedback_revisions(outcomes, as_of=as_of)
    contexts = {
        (
            item.action_type_id,
            item.prediction_snapshot.metric,
            item.prediction_snapshot.unit,
            item.prediction_snapshot.model_ref,
            item.prediction_snapshot.model_digest,
            item.prediction_snapshot.objective,
            item.prediction_snapshot.observation_deadline - item.prediction_snapshot.predicted_at,
            item.prediction_snapshot.nominal_coverage,
        )
        for item in latest
        if item.prediction_snapshot is not None
    }
    if len(contexts) > 1:
        raise ValueError("mixed prediction contexts require separate evaluation")
    groups: dict[str, list[ResponseOutcome]] = {}
    unavailable = 0
    for outcome in latest:
        snapshot = outcome.prediction_snapshot
        if snapshot is None:
            unavailable += 1
            continue
        groups.setdefault(snapshot.independence_key, []).append(outcome)
    errors: list[float] = []
    widths: list[float] = []
    covered = 0
    held = unavailable
    for key, group in groups.items():
        if key in training_independence_keys or len(group) != 1:
            held += 1
            continue
        outcome = group[0]
        snapshot = outcome.prediction_snapshot
        if (
            snapshot is None
            or not outcome.scorable
            or outcome.observed_value is None
            or not outcome.observation_receipt_ref
            or outcome.observation_unit != snapshot.unit
            or outcome.observed_at is None
            or outcome.observed_at <= snapshot.predicted_at
            or outcome.execution_mode.value != "enforce"
            or outcome.decision not in {"auto", "hil"}
            or execution_lifecycle_disposition(outcome.execution_outcome)
            is not ExecutionLifecycleDisposition.ACCEPTED
            or outcome.rollback_succeeded is not False
        ):
            held += 1
            continue
        error = abs(snapshot.point_prediction - outcome.observed_value)
        width = snapshot.interval_upper - snapshot.interval_lower
        if not math.isfinite(error) or not math.isfinite(width):
            raise ValueError("prediction evaluation arithmetic MUST remain finite")
        errors.append(error)
        widths.append(width)
        covered += snapshot.interval_lower <= outcome.observed_value <= snapshot.interval_upper
    scored = len(errors)
    mae = math.fsum(error / scored for error in errors) if scored else None
    mean_width = math.fsum(width / scored for width in widths) if scored else None
    return PrequentialEvaluation(
        len(latest),
        len(groups),
        scored,
        held,
        mae,
        covered / scored if scored else None,
        mean_width,
        source_kind,
    )
