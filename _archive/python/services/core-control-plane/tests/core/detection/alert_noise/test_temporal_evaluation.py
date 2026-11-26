"""Exact uniform detector replay, per-case safety guards, and inert temporal plans."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.planning import AlertPlanHeld, plan_alert_change
from fdai.core.detection.alert_noise.temporal_evaluation import compare_temporal_evaluation
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy
from fdai_service_contracts.alert_noise_evaluation import (
    EvaluationCaseResult,
    EvaluationReceipt,
    EvaluationSeries,
    TemporalEvaluationScenarioSet,
    evaluation_method_matches,
)
from fdai_service_contracts.alert_noise_plan import AlertTreatment
from pydantic import ValidationError


def _series(
    now: datetime, *, ref: str, values: tuple[float, ...], positive: bool
) -> EvaluationSeries:
    start = now - timedelta(minutes=20)
    return EvaluationSeries(
        ref=ref,
        starts_at=start,
        sample_seconds=60,
        values=values,
        evaluation_start=start + timedelta(minutes=10),
        evaluation_end=now,
        actionable_at=start + timedelta(minutes=10) if positive else None,
        label_source_ref="source:independent-labels",
        label_revision="sha256:" + "c" * 64,
        complete=True,
    )


def _cohort(now: datetime, evidence: AlertEvidence, *, frequency: bool = False):
    negative = (
        (0.0,) * 8 + (-450.0, 450.0) + (0.0,) * 10
        if frequency
        else ((0.0,) * 10 + (100.0,) + (0.0,) * 9)
    )
    return TemporalEvaluationScenarioSet(
        rule_ref=evidence.rules[0].ref,
        rule_revision=evidence.rules[0].revision,
        source_ref="source:uniform-metric",
        reviewer_ref="person:independent-reviewer",
        cutoff=now,
        series=(
            _series(now, ref="case:positive", values=(100.0,) * 20, positive=True),
            _series(now, ref="case:negative", values=negative, positive=False),
        ),
    )


def _configs(evidence: AlertEvidence, *, frequency: bool = False):
    baseline = evidence.rules[0].evaluation.model_copy(
        update={"window_seconds": 300 if frequency else 60, "frequency_seconds": 60}
    )
    treatment = baseline.model_copy(
        update={"frequency_seconds" if frequency else "window_seconds": 300}
    )
    return baseline, treatment


@pytest.mark.parametrize("frequency", [False, True])
def test_temporal_replay_binds_equal_exposure_and_latency(evidence, now, frequency):
    baseline, treatment = _configs(evidence, frequency=frequency)
    cohort = _cohort(now, evidence, frequency=frequency)
    receipt = compare_temporal_evaluation(cohort, baseline=baseline, treatment=treatment, now=now)
    assert receipt.accepted and evaluation_method_matches(receipt)
    assert receipt.baseline_false_positive == 1 and receipt.treatment_false_positive == 0
    assert receipt.baseline_true_positive == receipt.treatment_true_positive == 1
    assert receipt.baseline_max_latency_seconds == receipt.treatment_max_latency_seconds == 0
    assert receipt.case_results[1].baseline_latency_seconds is None
    assert receipt.execution_authority is False
    assert EvaluationReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    assert TemporalEvaluationScenarioSet.model_validate_json(cohort.model_dump_json()) == cohort


def test_temporal_plan_requires_current_matching_method(evidence, now):
    baseline, candidate = _configs(evidence)
    evidence = evidence.model_copy(
        update={"rules": (evidence.rules[0].model_copy(update={"evaluation": baseline}),)}
    )
    receipt = compare_temporal_evaluation(
        _cohort(now, evidence), baseline=baseline, treatment=candidate, now=now
    )
    treatment = AlertTreatment(
        kind="evaluation", target_ref=evidence.rules[0].ref, evaluation=candidate
    )
    plan = plan_alert_change(
        evidence,
        treatment,
        policy=NoisePolicy(),
        requester_ref="person:requester",
        now=now,
        evaluation_receipt=receipt,
    )
    assert plan.action_type == "ops.tune-alert-evaluation" and plan.default_mode == "shadow"
    assert plan.quorum_required == 2 and plan.execution_authority is False
    with pytest.raises(AlertPlanHeld, match="evaluation_validation_missing"):
        plan_alert_change(
            evidence, treatment, policy=NoisePolicy(), requester_ref="person:requester", now=now
        )
    forged = receipt.model_copy(
        update={
            "replay_method": "same-bucket-threshold-v1",
            "case_results": (),
            "baseline_max_latency_seconds": None,
            "treatment_max_latency_seconds": None,
        }
    )
    with pytest.raises(AlertPlanHeld):
        plan_alert_change(
            evidence,
            treatment,
            policy=NoisePolicy(),
            requester_ref="person:requester",
            now=now,
            evaluation_receipt=forged,
        )


def test_different_native_kind_stays_held(evidence, now):
    baseline, candidate = _configs(evidence)
    evidence = evidence.model_copy(
        update={
            "rules": (evidence.rules[0].model_copy(update={"kind": "log", "evaluation": baseline}),)
        }
    )
    receipt = compare_temporal_evaluation(
        _cohort(now, evidence), baseline=baseline, treatment=candidate, now=now
    )
    with pytest.raises(AlertPlanHeld, match="single_axis"):
        plan_alert_change(
            evidence,
            AlertTreatment(
                kind="evaluation", target_ref=evidence.rules[0].ref, evaluation=candidate
            ),
            policy=NoisePolicy(),
            requester_ref="person:requester",
            now=now,
            evaluation_receipt=receipt,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"complete": 1},
        {"values": (0.0,) * 19},
        {"values": (float("nan"),) * 20},
        {"sample_seconds": True},
    ],
)
def test_series_rejects_missing_irregular_or_coerced_evidence(now, change):
    payload = _series(now, ref="case:one", values=(0.0,) * 20, positive=False).model_dump()
    with pytest.raises(ValidationError):
        EvaluationSeries.model_validate({**payload, **change})


@pytest.mark.parametrize(
    "change",
    [
        {"starts_at": 0},
        {"evaluation_start": 0},
        {"evaluation_end": 0},
        {"actionable_at": 0},
    ],
)
def test_series_does_not_coerce_numeric_time(now, change):
    payload = _series(now, ref="case:one", values=(0.0,) * 20, positive=False).model_dump()
    with pytest.raises(ValidationError):
        EvaluationSeries.model_validate({**payload, **change})


@pytest.mark.parametrize(
    "field,offset",
    [
        ("evaluation_start", -1200),
        ("evaluation_start", 0),
        ("evaluation_start", -601),
        ("actionable_at", -601),
        ("actionable_at", 0),
        ("actionable_at", -599),
    ],
)
def test_series_time_boundaries_are_exact(now, field, offset):
    payload = _series(now, ref="case:one", values=(0.0,) * 20, positive=False).model_dump()
    with pytest.raises(ValidationError):
        EvaluationSeries.model_validate({**payload, field: now + timedelta(seconds=offset)})


@pytest.mark.parametrize(
    "change", ["same-reviewer", "duplicate", "only-negative", "future", "budget"]
)
def test_cohort_rejects_unreviewed_or_incomplete_exposure(evidence, now, change):
    cohort = _cohort(now, evidence)
    updates = {
        "same-reviewer": {"reviewer_ref": cohort.source_ref},
        "duplicate": {"series": (cohort.series[0], cohort.series[0], cohort.series[1])},
        "only-negative": {
            "series": (cohort.series[1], cohort.series[1].model_copy(update={"ref": "case:other"}))
        },
        "future": {"cutoff": now - timedelta(seconds=1)},
    }
    if change == "budget":
        large = cohort.series[0].model_copy(
            update={"values": (1.0,) * 10000, "starts_at": now - timedelta(seconds=600000)}
        )
        updates[change] = {
            "series": tuple(large.model_copy(update={"ref": f"case:{i}"}) for i in range(26))
        }
    with pytest.raises(ValidationError):
        TemporalEvaluationScenarioSet.model_validate(cohort.model_copy(update=updates[change]))


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"threshold": 90.0},
        {"window_seconds": 300, "threshold": 90.0},
        {"window_seconds": 301},
        {"window_seconds": 900},
        {"frequency_seconds": 300},
    ],
)
def test_temporal_replay_rejects_mixed_or_unsupported_exposure(evidence, now, change):
    baseline, _ = _configs(evidence)
    with pytest.raises(ValueError):
        compare_temporal_evaluation(
            _cohort(now, evidence),
            baseline=baseline,
            treatment=baseline.model_copy(update=change),
            now=now,
        )


@pytest.mark.parametrize("clock", ["naive", "future"])
def test_temporal_replay_requires_trusted_current_clock(evidence, now, clock):
    baseline, treatment = _configs(evidence)
    with pytest.raises(ValueError, match="cutoff"):
        compare_temporal_evaluation(
            _cohort(now, evidence),
            baseline=baseline,
            treatment=treatment,
            now=now.replace(tzinfo=None) if clock == "naive" else now - timedelta(seconds=1),
        )


def test_early_positive_is_unscorable_not_a_fast_detection(evidence, now):
    cohort = _cohort(now, evidence)
    positive = cohort.series[0].model_copy(update={"actionable_at": now - timedelta(minutes=8)})
    baseline, treatment = _configs(evidence)
    with pytest.raises(ValueError, match="before"):
        compare_temporal_evaluation(
            cohort.model_copy(update={"series": (positive, cohort.series[1])}),
            baseline=baseline,
            treatment=treatment,
            now=now,
        )


@pytest.mark.parametrize("aggregation", ["minimum", "maximum"])
def test_no_measured_benefit_does_not_get_accepted(evidence, now, aggregation):
    baseline, treatment = _configs(evidence)
    receipt = compare_temporal_evaluation(
        _cohort(now, evidence),
        baseline=baseline.model_copy(update={"aggregation": aggregation}),
        treatment=treatment.model_copy(update={"aggregation": aggregation}),
        now=now,
    )
    assert receipt.accepted is (aggregation == "minimum")


def test_below_detector_is_not_inverted(evidence, now):
    cohort = _cohort(now, evidence)
    cohort = cohort.model_copy(
        update={
            "series": tuple(
                row.model_copy(update={"values": tuple(-value for value in row.values)})
                for row in cohort.series
            )
        }
    )
    baseline, treatment = _configs(evidence)
    receipt = compare_temporal_evaluation(
        cohort,
        baseline=baseline.model_copy(update={"operator": "below", "threshold": -80.0}),
        treatment=treatment.model_copy(update={"operator": "below", "threshold": -80.0}),
        now=now,
    )
    assert receipt.accepted and receipt.treatment_false_positive == 0


@pytest.mark.parametrize("missing", [False, True])
def test_no_detected_positive_is_not_zero_latency(evidence, now, missing):
    cohort = _cohort(now, evidence)
    values = (0.0,) * 10 + (100.0,) + (0.0,) * 9 if missing else (0.0,) * 20
    cohort = cohort.model_copy(
        update={
            "series": (cohort.series[0].model_copy(update={"values": values}), cohort.series[1])
        }
    )
    baseline, treatment = _configs(evidence)
    receipt = compare_temporal_evaluation(cohort, baseline=baseline, treatment=treatment, now=now)
    assert not receipt.accepted
    assert receipt.treatment_max_latency_seconds is None and receipt.treatment_false_negative == 1


def test_receipt_rejects_aggregate_that_hides_one_delayed_positive(evidence, now):
    baseline, treatment = _configs(evidence)
    good = compare_temporal_evaluation(
        _cohort(now, evidence), baseline=baseline, treatment=treatment, now=now
    )
    cases = (
        good.case_results[0].model_copy(
            update={"baseline_latency_seconds": 60, "treatment_latency_seconds": 0}
        ),
        good.case_results[1],
        EvaluationCaseResult(
            ref="case:delayed",
            actionable=True,
            baseline_detected=True,
            treatment_detected=True,
            baseline_latency_seconds=0,
            treatment_latency_seconds=60,
        ),
    )
    payload = {
        **good.model_dump(),
        "case_results": cases,
        "baseline_true_positive": 2,
        "treatment_true_positive": 2,
        "baseline_max_latency_seconds": 60,
        "treatment_max_latency_seconds": 60,
    }
    with pytest.raises(ValidationError, match="acceptance"):
        EvaluationReceipt.model_validate(payload)
    receipt = EvaluationReceipt.model_validate({**payload, "accepted": False})
    assert not receipt.accepted and cases[2].positive_regressed


@pytest.mark.parametrize(
    "change",
    [
        {"baseline_true_positive": 2},
        {"baseline_max_latency_seconds": 1},
        {"case_results": ()},
        {"replay_method": "same-bucket-threshold-v1"},
        {"execution_authority": True},
    ],
)
def test_receipt_cannot_launder_counts_latency_or_authority(evidence, now, change):
    baseline, treatment = _configs(evidence)
    receipt = compare_temporal_evaluation(
        _cohort(now, evidence), baseline=baseline, treatment=treatment, now=now
    )
    with pytest.raises(ValidationError):
        EvaluationReceipt.model_validate({**receipt.model_dump(), **change})


def test_replay_work_budget_prevents_expensive_window_expansion(evidence, now):
    cohort = _cohort(now, evidence)
    cohort = cohort.model_copy(
        update={
            "series": tuple(
                row.model_copy(
                    update={
                        "starts_at": now - timedelta(seconds=10000),
                        "sample_seconds": 1,
                        "values": (100.0,) * 10000,
                        "evaluation_start": now - timedelta(seconds=5000),
                    }
                )
                for row in cohort.series
            )
        }
    )
    baseline = evidence.rules[0].evaluation.model_copy(
        update={"window_seconds": 4999, "frequency_seconds": 1}
    )
    with pytest.raises(ValueError, match="computation budget"):
        compare_temporal_evaluation(
            cohort,
            baseline=baseline,
            treatment=baseline.model_copy(update={"window_seconds": 5000}),
            now=now,
        )
