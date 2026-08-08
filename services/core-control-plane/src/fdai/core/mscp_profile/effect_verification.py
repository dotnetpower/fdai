"""Deterministic effect verification for the MSCP operational profile.

MSCP provenance: Level 3 prediction gating. FDAI adapts the mechanism to
compare an expected substrate effect with an independently observed value.
This module does not execute, approve, roll back, or write audit records.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EffectVerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    HOLD = "hold"


class EffectVerificationReason(StrEnum):
    WITHIN_ACCEPTABLE_RANGE = "within_acceptable_range"
    VALUE_OUTSIDE_ACCEPTABLE_RANGE = "value_outside_acceptable_range"
    PREDICTION_ID_MISMATCH = "prediction_id_mismatch"
    TARGET_MISMATCH = "target_mismatch"
    METRIC_MISMATCH = "metric_mismatch"
    OBSERVATION_BEFORE_PREDICTION = "observation_before_prediction"
    OBSERVATION_AFTER_DEADLINE = "observation_after_deadline"
    PREDICTION_UNAVAILABLE = "prediction_unavailable"
    PREDICTION_PROVIDER_FAILED = "prediction_provider_failed"
    PREDICTION_TARGET_MISMATCH = "prediction_target_mismatch"
    OBSERVATION_UNAVAILABLE = "observation_unavailable"
    OBSERVATION_PROVIDER_FAILED = "observation_provider_failed"


def _require_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} MUST be non-empty")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} MUST be finite")


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExpectedEffect:
    """One bounded, time-limited prediction for a target metric."""

    prediction_id: str
    target_ref: str
    metric: str
    acceptable_min: float
    acceptable_max: float
    predicted_at: datetime
    observation_deadline: datetime

    def __post_init__(self) -> None:
        _require_non_empty("prediction_id", self.prediction_id)
        _require_non_empty("target_ref", self.target_ref)
        _require_non_empty("metric", self.metric)
        _require_finite("acceptable_min", self.acceptable_min)
        _require_finite("acceptable_max", self.acceptable_max)
        if self.acceptable_min > self.acceptable_max:
            raise ValueError("acceptable_min MUST be <= acceptable_max")
        _require_aware("predicted_at", self.predicted_at)
        _require_aware("observation_deadline", self.observation_deadline)
        if self.observation_deadline < self.predicted_at:
            raise ValueError("observation_deadline MUST NOT precede predicted_at")


@dataclass(frozen=True, slots=True)
class ObservedEffect:
    """One independently observed value correlated to a prediction."""

    prediction_id: str
    target_ref: str
    metric: str
    value: float
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty("prediction_id", self.prediction_id)
        _require_non_empty("target_ref", self.target_ref)
        _require_non_empty("metric", self.metric)
        _require_finite("value", self.value)
        _require_aware("observed_at", self.observed_at)


@dataclass(frozen=True, slots=True)
class EffectVerificationResult:
    status: EffectVerificationStatus
    reason: EffectVerificationReason


def verify_effect(
    expected: ExpectedEffect,
    observed: ObservedEffect,
) -> EffectVerificationResult:
    """Compare one expected effect with one observation and fail toward review."""

    if observed.prediction_id != expected.prediction_id:
        return EffectVerificationResult(
            EffectVerificationStatus.HOLD,
            EffectVerificationReason.PREDICTION_ID_MISMATCH,
        )
    if observed.target_ref != expected.target_ref:
        return EffectVerificationResult(
            EffectVerificationStatus.HOLD,
            EffectVerificationReason.TARGET_MISMATCH,
        )
    if observed.metric != expected.metric:
        return EffectVerificationResult(
            EffectVerificationStatus.HOLD,
            EffectVerificationReason.METRIC_MISMATCH,
        )
    if observed.observed_at < expected.predicted_at:
        return EffectVerificationResult(
            EffectVerificationStatus.HOLD,
            EffectVerificationReason.OBSERVATION_BEFORE_PREDICTION,
        )
    if observed.observed_at > expected.observation_deadline:
        return EffectVerificationResult(
            EffectVerificationStatus.HOLD,
            EffectVerificationReason.OBSERVATION_AFTER_DEADLINE,
        )
    if not expected.acceptable_min <= observed.value <= expected.acceptable_max:
        return EffectVerificationResult(
            EffectVerificationStatus.MISMATCH,
            EffectVerificationReason.VALUE_OUTSIDE_ACCEPTABLE_RANGE,
        )
    return EffectVerificationResult(
        EffectVerificationStatus.VERIFIED,
        EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE,
    )


__all__ = [
    "EffectVerificationReason",
    "EffectVerificationResult",
    "EffectVerificationStatus",
    "ExpectedEffect",
    "ObservedEffect",
    "verify_effect",
]
