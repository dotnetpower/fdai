from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.detection.forecast_outcome import (
    ForecastExpectation,
    ForecastObservation,
    close_forecast,
    close_missed_breach,
)
from fdai.shared.contracts.models import ForecastOutcomeLabel, TelemetryCompleteness

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _expectation() -> ForecastExpectation:
    return ForecastExpectation(
        prediction_id=UUID(int=1),
        correlation_id="corr-1",
        detector_id="capacity-linear",
        detector_version="1.0.0",
        access_scope_digest="a" * 64,
        target_ref="resource-1",
        metric="capacity_percent",
        feature_cutoff=T0,
        horizon_started_at=T0,
        horizon_ended_at=T0 + timedelta(hours=1),
        direction="rising",
        threshold=90.0,
        predicted_value=95.0,
        interval_lower=91.0,
        interval_upper=99.0,
        evidence_refs=("forecast:1",),
    )


def test_close_forecast_labels_intervention_without_penalizing_precision() -> None:
    outcome = close_forecast(
        _expectation(),
        ForecastObservation(
            observed_value=70.0,
            actual_breach_at=None,
            telemetry_completeness=TelemetryCompleteness.COMPLETE,
            evidence_refs=("observation:1",),
            intervention_refs=("action:1",),
        ),
        closed_at=T0 + timedelta(hours=2),
    )
    assert outcome.label is ForecastOutcomeLabel.INTERVENTION_CENSORED
    assert outcome.evidence_refs == ("forecast:1", "observation:1")


def test_close_forecast_labels_partial_telemetry_unscorable() -> None:
    outcome = close_forecast(
        _expectation(),
        ForecastObservation(
            observed_value=None,
            actual_breach_at=None,
            telemetry_completeness=TelemetryCompleteness.PARTIAL,
            evidence_refs=("provider-error:1",),
        ),
        closed_at=T0 + timedelta(hours=2),
    )
    assert outcome.label is ForecastOutcomeLabel.UNSCORABLE


def test_close_missed_breach_is_stable_false_negative() -> None:
    kwargs = dict(
        correlation_id="corr-2",
        detector_id="capacity-linear",
        detector_version="1.0.0",
        access_scope_digest="a" * 64,
        target_ref="resource-2",
        metric="capacity_percent",
        feature_cutoff=T0,
        horizon_started_at=T0,
        horizon_ended_at=T0 + timedelta(hours=1),
        direction="rising",
        threshold=90.0,
        observed_value=96.0,
        actual_breach_at=T0 + timedelta(minutes=30),
        evidence_refs=("breach:1",),
        closed_at=T0 + timedelta(hours=2),
    )
    first = close_missed_breach(**kwargs)
    second = close_missed_breach(**kwargs)
    assert first.label is ForecastOutcomeLabel.FALSE_NEGATIVE
    assert first.outcome_id == second.outcome_id
    assert (
        first.outcome_id
        != close_missed_breach(**{**kwargs, "access_scope_digest": "b" * 64}).outcome_id
    )
