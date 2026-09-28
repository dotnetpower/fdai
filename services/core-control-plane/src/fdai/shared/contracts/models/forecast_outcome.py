"""Terminal forecast-outcome contract for the agent event bus."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from ._base import IdempotencyKey, SemVer, _Base
from .enums import Mode

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1, max_length=512)]


class ForecastScoringExclusion(StrEnum):
    """Canonical reasons a measured forecast cannot enter untreated scoring.

    The ``operational_evidence_*`` members name an explicit independent-evidence rejection
    class and exist only in schema ``1.2.0``, where each one cites its rejection record.
    """

    INTERVENTION_HISTORY_UNAVAILABLE = "intervention_history_unavailable"
    CONTEXT_MISMATCH = "context_mismatch"
    EXCLUDED_WINDOW = "excluded_window"
    RESOURCE_DELETED = "resource_deleted"
    INTERVENTION_AFFECTED = "intervention_affected"
    OPERATIONAL_EVIDENCE_CONFLICTING = "operational_evidence_conflicting"
    OPERATIONAL_EVIDENCE_CROSS_SCOPE = "operational_evidence_cross_scope"
    OPERATIONAL_EVIDENCE_PARTIAL = "operational_evidence_partial"
    OPERATIONAL_EVIDENCE_REPLAY_SUBSTITUTED = "operational_evidence_replay_substituted"
    OPERATIONAL_EVIDENCE_REVOKED = "operational_evidence_revoked"
    OPERATIONAL_EVIDENCE_STALE = "operational_evidence_stale"
    OPERATIONAL_EVIDENCE_SYNTHETIC_LIVE = "operational_evidence_synthetic_live"


_EVIDENCE_EXCLUSIONS = frozenset(
    item for item in ForecastScoringExclusion if item.value.startswith("operational_evidence_")
)
_REJECTION_REF = re.compile(r"^operational-evidence-rejection:sha256:[0-9a-f]{64}$")


class ForecastOutcomeLabel(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    LATE_BREACH = "late_breach"
    MAGNITUDE_ERROR = "magnitude_error"
    INTERVENTION_CENSORED = "intervention_censored"
    UNSCORABLE = "unscorable"


class TelemetryCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ForecastMissOrigin(StrEnum):
    MODEL = "model"
    PIPELINE = "pipeline"


class ForecastOutcome(_Base):
    """One immutable terminal result for a forecast or missed breach."""

    schema_version: SemVer
    outcome_id: UUID
    idempotency_key: IdempotencyKey
    correlation_id: NonEmpty
    prediction_id: UUID | None = None
    detector_id: NonEmpty
    detector_version: SemVer
    access_scope_digest: Digest
    target_digest: Digest
    metric: NonEmpty
    feature_cutoff: datetime
    horizon_started_at: datetime
    horizon_ended_at: datetime
    direction: Literal["rising", "falling"]
    threshold: float
    predicted_value: float | None = None
    interval_lower: float | None = None
    interval_upper: float | None = None
    observed_value: float | None = None
    actual_breach_at: datetime | None = None
    label: ForecastOutcomeLabel
    miss_origin: ForecastMissOrigin | None = None
    intervention_refs: tuple[NonEmpty, ...] = ()
    evidence_refs: Annotated[tuple[NonEmpty, ...], Field(min_length=1)]
    telemetry_completeness: TelemetryCompleteness
    closed_at: datetime
    mode: Mode = Mode.SHADOW
    scoring_exclusions: Annotated[tuple[ForecastScoringExclusion, ...], Field(max_length=5)] = ()

    @model_serializer(mode="wrap")
    def _serialize_version(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Keep the legacy wire shape while allowing explicit v1.1+ scoring exclusions."""
        payload: dict[str, object] = dict(handler(self))
        if self.schema_version == "1.0.0":
            payload.pop("scoring_exclusions", None)
        return payload

    @model_validator(mode="after")
    def _validate_semantics(self) -> ForecastOutcome:
        if self.schema_version not in {"1.0.0", "1.1.0", "1.2.0"}:
            raise ValueError("forecast outcome schema version is unsupported")
        if self.scoring_exclusions:
            if self.schema_version == "1.0.0":
                raise ValueError("forecast scoring exclusions require schema version 1.1.0")
            if self.label is not ForecastOutcomeLabel.UNSCORABLE:
                raise ValueError("excluded forecast observations MUST be unscorable")
            if len(set(self.scoring_exclusions)) != len(self.scoring_exclusions):
                raise ValueError("forecast scoring exclusions MUST be unique")
        evidence_classes = [
            item for item in self.scoring_exclusions if item in _EVIDENCE_EXCLUSIONS
        ]
        rejection_refs = [
            item
            for item in self.evidence_refs
            if item.startswith("operational-evidence-rejection:")
        ]
        if evidence_classes and self.schema_version != "1.2.0":
            raise ValueError("operational evidence exclusions require schema version 1.2.0")
        if len(evidence_classes) > 1:
            raise ValueError("a forecast outcome names at most one operational evidence class")
        if len(rejection_refs) != len(evidence_classes) or any(
            _REJECTION_REF.fullmatch(item) is None for item in rejection_refs
        ):
            raise ValueError(
                "an operational evidence exclusion MUST cite exactly one rejection record"
            )
        timestamps = (
            self.feature_cutoff,
            self.horizon_started_at,
            self.horizon_ended_at,
            self.closed_at,
        )
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("forecast outcome timestamps MUST be timezone-aware")
        if not (
            self.feature_cutoff
            <= self.horizon_started_at
            <= self.horizon_ended_at
            <= self.closed_at
        ):
            raise ValueError("forecast outcome timestamps MUST be ordered")
        if self.actual_breach_at is not None and self.actual_breach_at.tzinfo is None:
            raise ValueError("actual_breach_at MUST be timezone-aware")
        if self.actual_breach_at is not None and not (
            self.feature_cutoff <= self.actual_breach_at <= self.closed_at
        ):
            raise ValueError("actual_breach_at MUST fall between feature cutoff and close time")
        numeric = (
            self.threshold,
            self.predicted_value,
            self.interval_lower,
            self.interval_upper,
            self.observed_value,
        )
        if any(value is not None and not isfinite(value) for value in numeric):
            raise ValueError("forecast outcome numeric evidence MUST be finite")
        if (self.interval_lower is None) != (self.interval_upper is None):
            raise ValueError("forecast interval bounds MUST be supplied together")
        if (
            self.interval_lower is not None
            and self.interval_upper is not None
            and self.interval_lower > self.interval_upper
        ):
            raise ValueError("forecast interval lower bound MUST NOT exceed upper bound")
        if self.label is ForecastOutcomeLabel.FALSE_NEGATIVE:
            if self.prediction_id is not None or self.actual_breach_at is None:
                raise ValueError("false-negative outcome MUST be an unpredicted actual breach")
            if any(
                value is not None
                for value in (self.predicted_value, self.interval_lower, self.interval_upper)
            ):
                raise ValueError("false-negative outcome MUST NOT carry prediction evidence")
            if self.miss_origin is None:
                raise ValueError("false-negative outcome MUST identify its miss origin")
        elif self.prediction_id is None:
            raise ValueError("non-false-negative outcome MUST reference a prediction")
        elif self.miss_origin is not None:
            raise ValueError("non-false-negative outcome MUST NOT carry a miss origin")
        if (
            self.label
            in {
                ForecastOutcomeLabel.TRUE_POSITIVE,
                ForecastOutcomeLabel.LATE_BREACH,
                ForecastOutcomeLabel.MAGNITUDE_ERROR,
            }
            and self.actual_breach_at is None
        ):
            raise ValueError("breach outcome MUST carry actual_breach_at")
        if (
            self.label is ForecastOutcomeLabel.TRUE_POSITIVE
            and self.actual_breach_at is not None
            and not self.horizon_started_at <= self.actual_breach_at <= self.horizon_ended_at
        ):
            raise ValueError("true-positive breach MUST fall inside the forecast horizon")
        if (
            self.label is ForecastOutcomeLabel.LATE_BREACH
            and self.actual_breach_at is not None
            and self.actual_breach_at <= self.horizon_ended_at
        ):
            raise ValueError("late-breach outcome MUST occur after the forecast horizon")
        if (
            self.label
            in {
                ForecastOutcomeLabel.FALSE_POSITIVE,
                ForecastOutcomeLabel.INTERVENTION_CENSORED,
            }
            and self.actual_breach_at is not None
        ):
            raise ValueError("non-breach outcome MUST NOT carry actual_breach_at")
        if self.label is ForecastOutcomeLabel.INTERVENTION_CENSORED and not self.intervention_refs:
            raise ValueError("intervention-censored outcome MUST reference an intervention")
        if self.label is ForecastOutcomeLabel.FALSE_POSITIVE and self.intervention_refs:
            raise ValueError("prevented breach MUST be intervention-censored")
        if self.label is ForecastOutcomeLabel.MAGNITUDE_ERROR:
            if (
                self.observed_value is None
                or self.interval_lower is None
                or self.interval_upper is None
            ):
                raise ValueError("magnitude-error outcome MUST carry observation and interval")
            if self.actual_breach_at is not None and not (
                self.horizon_started_at <= self.actual_breach_at <= self.horizon_ended_at
            ):
                raise ValueError("magnitude-error breach MUST fall inside the forecast horizon")
            if self.interval_lower <= self.observed_value <= self.interval_upper:
                raise ValueError("magnitude-error observation MUST fall outside the interval")
        if (
            self.telemetry_completeness is not TelemetryCompleteness.COMPLETE
            and self.label is not ForecastOutcomeLabel.UNSCORABLE
        ):
            raise ValueError("incomplete telemetry MUST be unscorable")
        if (
            self.label is ForecastOutcomeLabel.UNSCORABLE
            and self.telemetry_completeness is TelemetryCompleteness.COMPLETE
            and not self.scoring_exclusions
        ):
            raise ValueError("unscorable outcome MUST NOT claim complete telemetry")
        return self


__all__ = [
    "ForecastOutcome",
    "ForecastOutcomeLabel",
    "ForecastMissOrigin",
    "TelemetryCompleteness",
    "ForecastScoringExclusion",
]
