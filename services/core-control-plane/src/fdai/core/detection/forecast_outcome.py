"""Deterministic closure of forecasts and unpredicted breaches."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.contracts.models import (
    ForecastMissOrigin,
    ForecastOutcome,
    ForecastOutcomeLabel,
    Mode,
    TelemetryCompleteness,
)


@dataclass(frozen=True, slots=True)
class ForecastExpectation:
    prediction_id: UUID
    correlation_id: str
    detector_id: str
    detector_version: str
    access_scope_digest: str
    target_ref: str
    metric: str
    feature_cutoff: datetime
    horizon_started_at: datetime
    horizon_ended_at: datetime
    direction: Literal["rising", "falling"]
    threshold: float
    predicted_value: float
    interval_lower: float
    interval_upper: float
    evidence_refs: tuple[str, ...]
    mode: Mode = Mode.SHADOW


@dataclass(frozen=True, slots=True)
class ForecastObservation:
    observed_value: float | None
    actual_breach_at: datetime | None
    telemetry_completeness: TelemetryCompleteness
    evidence_refs: tuple[str, ...]
    intervention_refs: tuple[str, ...] = ()


def close_forecast(
    expectation: ForecastExpectation,
    observation: ForecastObservation,
    *,
    closed_at: datetime,
) -> ForecastOutcome:
    label = _label(expectation, observation)
    outcome_id = uuid5(
        NAMESPACE_URL,
        "fdai-forecast-outcome:"
        f"{expectation.prediction_id}:{expectation.horizon_ended_at.isoformat()}",
    )
    return ForecastOutcome(
        schema_version="1.0.0",
        outcome_id=outcome_id,
        idempotency_key=f"forecast-outcome:{outcome_id}",
        correlation_id=expectation.correlation_id,
        prediction_id=expectation.prediction_id,
        detector_id=expectation.detector_id,
        detector_version=expectation.detector_version,
        access_scope_digest=expectation.access_scope_digest,
        target_digest=hashlib.sha256(expectation.target_ref.encode()).hexdigest(),
        metric=expectation.metric,
        feature_cutoff=expectation.feature_cutoff,
        horizon_started_at=expectation.horizon_started_at,
        horizon_ended_at=expectation.horizon_ended_at,
        direction=expectation.direction,
        threshold=expectation.threshold,
        predicted_value=expectation.predicted_value,
        interval_lower=expectation.interval_lower,
        interval_upper=expectation.interval_upper,
        observed_value=observation.observed_value,
        actual_breach_at=observation.actual_breach_at,
        label=label,
        intervention_refs=observation.intervention_refs,
        evidence_refs=tuple(sorted(set(expectation.evidence_refs + observation.evidence_refs))),
        telemetry_completeness=observation.telemetry_completeness,
        closed_at=closed_at,
        mode=expectation.mode,
    )


def close_missed_breach(
    *,
    correlation_id: str,
    detector_id: str,
    detector_version: str,
    access_scope_digest: str,
    target_ref: str,
    metric: str,
    feature_cutoff: datetime,
    horizon_started_at: datetime,
    horizon_ended_at: datetime,
    direction: Literal["rising", "falling"],
    threshold: float,
    observed_value: float,
    actual_breach_at: datetime,
    evidence_refs: tuple[str, ...],
    closed_at: datetime,
    miss_origin: ForecastMissOrigin = ForecastMissOrigin.MODEL,
) -> ForecastOutcome:
    outcome_id = uuid5(
        NAMESPACE_URL,
        "fdai-missed-forecast:"
        f"{access_scope_digest}:{detector_id}:{detector_version}:"
        f"{target_ref}:{metric}:{actual_breach_at.isoformat()}",
    )
    return ForecastOutcome(
        schema_version="1.0.0",
        outcome_id=outcome_id,
        idempotency_key=f"forecast-outcome:{outcome_id}",
        correlation_id=correlation_id,
        prediction_id=None,
        detector_id=detector_id,
        detector_version=detector_version,
        access_scope_digest=access_scope_digest,
        target_digest=hashlib.sha256(target_ref.encode()).hexdigest(),
        metric=metric,
        feature_cutoff=feature_cutoff,
        horizon_started_at=horizon_started_at,
        horizon_ended_at=horizon_ended_at,
        direction=direction,
        threshold=threshold,
        observed_value=observed_value,
        actual_breach_at=actual_breach_at,
        label=ForecastOutcomeLabel.FALSE_NEGATIVE,
        miss_origin=miss_origin,
        evidence_refs=evidence_refs,
        telemetry_completeness=TelemetryCompleteness.COMPLETE,
        closed_at=closed_at,
    )


def _label(
    expectation: ForecastExpectation,
    observation: ForecastObservation,
) -> ForecastOutcomeLabel:
    if observation.telemetry_completeness is not TelemetryCompleteness.COMPLETE:
        return ForecastOutcomeLabel.UNSCORABLE
    if observation.intervention_refs and observation.actual_breach_at is None:
        return ForecastOutcomeLabel.INTERVENTION_CENSORED
    if observation.actual_breach_at is None:
        return ForecastOutcomeLabel.FALSE_POSITIVE
    if observation.actual_breach_at > expectation.horizon_ended_at:
        return ForecastOutcomeLabel.LATE_BREACH
    if observation.observed_value is not None and not (
        expectation.interval_lower <= observation.observed_value <= expectation.interval_upper
    ):
        return ForecastOutcomeLabel.MAGNITUDE_ERROR
    return ForecastOutcomeLabel.TRUE_POSITIVE


__all__ = [
    "ForecastExpectation",
    "ForecastObservation",
    "close_forecast",
    "close_missed_breach",
]
