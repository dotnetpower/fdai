from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEvaluationKind,
)
from fdai.core.ontology_platform.detection_projection import (
    forecast_object_record,
    pattern_object_record,
)
from fdai.core.operational_learning.patterns import OperatingPatternCandidate
from fdai.shared.providers.ontology_instance import (
    OntologyObjectRecord,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)
SCOPE_DIGEST = "a" * 64
FINGERPRINT = "b" * 64


def _episode(
    kind: ForecastEvaluationKind = ForecastEvaluationKind.PREDICTED_BREACH,
) -> ForecastEpisode:
    return ForecastEpisode(
        episode_id=uuid4(),
        correlation_id="forecast:example",
        detector_id="detector.example",
        detector_version="v1",
        scorer_version="scorer.v1",
        access_scope_digest=SCOPE_DIGEST,
        target_ref="resource-example",
        metric="cpu",
        feature_cutoff=NOW,
        horizon_started_at=NOW,
        horizon_ended_at=NOW + timedelta(seconds=600),
        telemetry_grace_seconds=60,
        direction="rising",
        threshold=90.0,
        evaluation_kind=kind,
        predicted_value=95.0 if kind is ForecastEvaluationKind.PREDICTED_BREACH else None,
        interval_lower=92.0 if kind is ForecastEvaluationKind.PREDICTED_BREACH else None,
        interval_upper=98.0 if kind is ForecastEvaluationKind.PREDICTED_BREACH else None,
        evidence_refs=("metric-window:example",),
        abstain_reason=None,
    )


def _candidate() -> OperatingPatternCandidate:
    return OperatingPatternCandidate(
        pattern_id=FINGERPRINT,
        failure_fingerprint=FINGERPRINT,
        resource_type="compute.vm",
        action_type="restart",
        sample_size=2,
        reusable_count=1,
        negative_count=1,
        outcome_counts=(("failure", 1), ("success", 1)),
        immutable_case_refs=("case-history:one:1:" + "c" * 64, "case-history:two:1:" + "d" * 64),
        digest_evidence=(FINGERPRINT,),
    )


def test_forecast_and_pattern_records_match_catalog_shapes() -> None:
    forecast = forecast_object_record(_episode(), confidence=0.9, issued_at=NOW)
    pattern = pattern_object_record(_candidate(), compiled_at=NOW)

    assert isinstance(forecast, OntologyObjectRecord)
    assert forecast.properties["horizon_seconds"] == 600
    assert forecast.properties["breach_predicate"] == "cpu:rising:90"
    assert pattern.properties["evidence_digest"].startswith("sha256:")
    assert pattern.properties["sample_size"] == 2


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (
            lambda: forecast_object_record(
                _episode(ForecastEvaluationKind.PREDICTED_NO_BREACH),
                confidence=0.9,
                issued_at=NOW,
            ),
            "only predicted",
        ),
        (
            lambda: forecast_object_record(_episode(), confidence=1.1, issued_at=NOW),
            "confidence",
        ),
    ),
)
def test_forecast_producer_rejects_unsupported_inputs(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
