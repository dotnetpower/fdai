from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEvaluationKind,
    forecast_episode_id,
)

T0 = datetime(2026, 7, 23, tzinfo=UTC)


def _episode(**overrides: object) -> ForecastEpisode:
    values: dict[str, object] = {
        "episode_id": forecast_episode_id(
            access_scope_digest="a" * 64,
            detector_id="capacity-linear",
            detector_version="1.0.0",
            target_ref="resource-1",
            metric="capacity_percent",
            feature_cutoff=T0,
            horizon_ended_at=T0 + timedelta(hours=1),
        ),
        "correlation_id": "corr-1",
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "scorer_version": "1.0.0",
        "access_scope_digest": "a" * 64,
        "target_ref": "resource-1",
        "metric": "capacity_percent",
        "feature_cutoff": T0,
        "horizon_started_at": T0,
        "horizon_ended_at": T0 + timedelta(hours=1),
        "telemetry_grace_seconds": 300,
        "direction": "rising",
        "threshold": 90.0,
        "evaluation_kind": ForecastEvaluationKind.PREDICTED_BREACH,
        "predicted_value": 95.0,
        "interval_lower": 91.0,
        "interval_upper": 99.0,
        "evidence_refs": ("metric-window:1",),
    }
    values.update(overrides)
    return ForecastEpisode(**values)  # type: ignore[arg-type]


def test_episode_identity_and_closure_policy_are_stable() -> None:
    first = _episode()
    second = _episode()
    assert first.episode_id == second.episode_id
    assert first.closure_due_at == T0 + timedelta(hours=1, minutes=5)
    assert len(first.target_digest) == 64


def test_abstain_is_distinct_from_negative_prediction() -> None:
    abstained = _episode(
        evaluation_kind=ForecastEvaluationKind.ABSTAINED,
        predicted_value=None,
        interval_lower=None,
        interval_upper=None,
        abstain_reason="insufficient_samples",
    )
    negative = _episode(
        evaluation_kind=ForecastEvaluationKind.PREDICTED_NO_BREACH,
        predicted_value=None,
        interval_lower=None,
        interval_upper=None,
    )
    assert abstained.evaluation_kind is ForecastEvaluationKind.ABSTAINED
    assert negative.evaluation_kind is ForecastEvaluationKind.PREDICTED_NO_BREACH


def test_non_positive_evaluation_rejects_prediction_evidence() -> None:
    with pytest.raises(ValueError, match="MUST NOT carry prediction evidence"):
        _episode(evaluation_kind=ForecastEvaluationKind.PREDICTED_NO_BREACH)
