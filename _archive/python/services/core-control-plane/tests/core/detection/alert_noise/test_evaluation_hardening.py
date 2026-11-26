"""Round 3: independently labeled replay, not a quieter detector, proves improvement."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.evaluation import compare_evaluation
from fdai_service_contracts.alert_noise import AlertEvidence
from fdai_service_contracts.alert_noise_evaluation import EvaluationSample, EvaluationScenarioSet


def scenarios(evidence: AlertEvidence, now: datetime) -> EvaluationScenarioSet:
    return EvaluationScenarioSet(
        rule_ref=evidence.rules[0].ref,
        rule_revision=evidence.rules[0].revision,
        source_ref="source:telemetry",
        reviewer_ref="principal:reviewer",
        cutoff=now,
        samples=tuple(
            EvaluationSample(
                ref=f"sample:{i}",
                observed_at=now - timedelta(minutes=5),
                values=values,
                actionable=actionable,
                label_source_ref="labels:independent",
                label_revision="sha256:" + "b" * 64,
                complete=True,
                window_seconds=300,
            )
            for i, (values, actionable) in enumerate((((95.0, 96.0), True), ((84.0, 85.0), False)))
        ),
    )


@pytest.mark.parametrize("aggregation", ["average", "maximum", "minimum"])
def test_replay_improves_noise_without_missed_positive(
    evidence: AlertEvidence, now: datetime, aggregation: str
) -> None:
    baseline = evidence.rules[0].evaluation.model_copy(update={"aggregation": aggregation})
    treatment = baseline.model_copy(update={"threshold": 90.0})
    receipt = compare_evaluation(
        scenarios(evidence, now), baseline=baseline, treatment=treatment, now=now
    )
    assert (
        receipt.accepted
        and receipt.baseline_false_positive == 1
        and receipt.treatment_false_positive == 0
    )
    assert receipt.baseline_true_positive == receipt.treatment_true_positive == 1
    assert receipt.execution_authority is False


def test_quieter_detector_losing_recall_is_rejected(evidence: AlertEvidence, now: datetime) -> None:
    baseline = evidence.rules[0].evaluation
    receipt = compare_evaluation(
        scenarios(evidence, now),
        baseline=baseline,
        treatment=baseline.model_copy(update={"threshold": 100.0}),
        now=now,
    )
    assert not receipt.accepted and receipt.treatment_false_negative == 1


def test_no_measured_benefit_is_not_accepted(evidence: AlertEvidence, now: datetime) -> None:
    baseline = evidence.rules[0].evaluation
    receipt = compare_evaluation(
        scenarios(evidence, now), baseline=baseline, treatment=baseline, now=now
    )
    assert not receipt.accepted


@pytest.mark.parametrize(
    "change", [{"window_seconds": 600}, {"frequency_seconds": 120}, {"metric_ref": "metric:other"}]
)
def test_replay_refuses_different_exposure_semantics(
    evidence: AlertEvidence, now: datetime, change: dict
) -> None:
    baseline = evidence.rules[0].evaluation
    with pytest.raises(ValueError, match="same-bucket"):
        compare_evaluation(
            scenarios(evidence, now),
            baseline=baseline,
            treatment=baseline.model_copy(update=change),
            now=now,
        )


def test_future_cutoff_and_wrong_bucket_are_rejected(
    evidence: AlertEvidence, now: datetime
) -> None:
    baseline = evidence.rules[0].evaluation
    with pytest.raises(ValueError, match="cutoff"):
        compare_evaluation(
            scenarios(evidence, now),
            baseline=baseline,
            treatment=baseline,
            now=now - timedelta(seconds=1),
        )
    wrong = scenarios(evidence, now).model_copy(
        update={
            "samples": tuple(
                row.model_copy(update={"window_seconds": 60})
                for row in scenarios(evidence, now).samples
            )
        }
    )
    with pytest.raises(ValueError, match="exposure"):
        compare_evaluation(wrong, baseline=baseline, treatment=baseline, now=now)


def test_below_threshold_semantics_are_not_inverted(evidence: AlertEvidence, now: datetime) -> None:
    baseline = evidence.rules[0].evaluation.model_copy(
        update={"operator": "below", "threshold": 100.0}
    )
    receipt = compare_evaluation(
        scenarios(evidence, now),
        baseline=baseline,
        treatment=baseline.model_copy(update={"threshold": 90.0}),
        now=now,
    )
    assert not receipt.accepted and receipt.treatment_false_negative == 1
