"""Tests for disjoint calibration/holdout causal evaluation and interval reporting."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.rca.evaluation import (
    CausalEvaluationCase,
    CausalEvaluationDisposition,
    CausalEvaluationEvidence,
    CausalEvaluationProvenance,
    CausalEvaluationResult,
)
from fdai.core.rca.holdout_report import (
    evaluate_disjoint_causal_holdout,
    wilson_interval,
)
from fdai.delivery.azure.catalog_causal_prediction_engine import (
    load_causal_prediction_scenario_catalog,
)
from fdai.runtime.causal_bindings import build_catalog_causal_grade_bridge

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
REV_LABEL = "sha256:" + "a" * 64
REV_RUNNER = "sha256:" + "b" * 64


def _build_scenario_cohort(
    round_codes: tuple[str, ...],
    held_round_codes: tuple[str, ...],
    prefix: str,
) -> tuple[tuple[CausalEvaluationCase, ...], tuple[CausalEvaluationResult, ...]]:
    bridge = build_catalog_causal_grade_bridge(repo_root=REPO_ROOT)
    catalog = load_causal_prediction_scenario_catalog(REPO_ROOT)
    cases: list[CausalEvaluationCase] = []
    results: list[CausalEvaluationResult] = []

    for code in round_codes:
        spec = catalog.get_by_round(code)
        graded = bridge.execute_and_grade_scenario(spec, base_time=NOW)
        hyp = graded.report.causal_result.hypothesis_record
        case_id = f"{prefix}.{code.lower()}"
        ev_refs = hyp.supporting_refs
        cases.append(
            CausalEvaluationCase(
                case_id=case_id,
                labeler_id="independent.sre.reviewer",
                label_source_revision=REV_LABEL,
                label_method="sanitized-incident-review-v1",
                label_provenance=CausalEvaluationProvenance.LOCAL_FIXTURE,
                expected_disposition=CausalEvaluationDisposition.SUPPORTED,
                expected_cause_ref=hyp.cause_ref,
                evidence=tuple(
                    CausalEvaluationEvidence(
                        ref=ref,
                        source_revision=REV_LABEL,
                        provenance=CausalEvaluationProvenance.LOCAL_FIXTURE,
                    )
                    for ref in ev_refs
                ),
            )
        )
        results.append(
            CausalEvaluationResult(
                case_id=case_id,
                actual_disposition=(
                    CausalEvaluationDisposition.SUPPORTED
                    if graded.hypothesis_supported
                    else CausalEvaluationDisposition.UNRESOLVED
                ),
                actual_cause_ref=hyp.cause_ref if graded.hypothesis_supported else None,
                cited_evidence_refs=ev_refs if graded.hypothesis_supported else (),
            )
        )

    for code in held_round_codes:
        spec = catalog.get_by_round(code)
        reviewed = bridge.resolve_mechanism(spec.causal_mechanisms[0])
        graded = bridge.execute_and_grade_scenario(
            spec,
            base_time=NOW,
            missing_refutation_reads=(reviewed.refutation_reads[0],),
            refutation_reads_run=(reviewed.refutation_reads[1],),
        )
        case_id = f"{prefix}.hold.{code.lower()}"
        cases.append(
            CausalEvaluationCase(
                case_id=case_id,
                labeler_id="independent.sre.reviewer",
                label_source_revision=REV_LABEL,
                label_method="sanitized-incident-review-v1",
                label_provenance=CausalEvaluationProvenance.LOCAL_FIXTURE,
                expected_disposition=CausalEvaluationDisposition.UNRESOLVED,
                expected_cause_ref=None,
                evidence=(),
            )
        )
        results.append(
            CausalEvaluationResult(
                case_id=case_id,
                actual_disposition=(
                    CausalEvaluationDisposition.SUPPORTED
                    if graded.hypothesis_supported
                    else CausalEvaluationDisposition.UNRESOLVED
                ),
                actual_cause_ref=(
                    graded.report.causal_result.hypothesis_record.cause_ref
                    if graded.hypothesis_supported
                    else None
                ),
                cited_evidence_refs=(),
            )
        )
    return tuple(cases), tuple(results)


def test_disjoint_calibration_and_holdout_report_accuracy_abstention_and_zero_wrong_action() -> (
    None
):
    cal_cases, cal_results = _build_scenario_cohort(
        round_codes=("D001", "D002", "D003", "D004", "D005", "D006"),
        held_round_codes=("D007", "D008"),
        prefix="cal",
    )
    hold_cases, hold_results = _build_scenario_cohort(
        round_codes=("D011", "D012", "D013", "D014", "D015", "D016", "D017", "D018"),
        held_round_codes=("D019", "D020", "D021", "D022"),
        prefix="holdout",
    )

    report = evaluate_disjoint_causal_holdout(
        calibration_cases=cal_cases,
        calibration_results=cal_results,
        holdout_cases=hold_cases,
        holdout_results=hold_results,
        runner_id="catalog-causal-grade-bridge",
        runner_source_revision=REV_RUNNER,
        runner_method="catalog-causal-inference-e8.v1",
    )

    assert report.deployed_qualification is False
    assert report.execution_authority is False
    assert report.report_digest.startswith("sha256:")
    assert report.holdout.root_cause_accuracy.rate == 1.0
    assert 0.7 < report.holdout.root_cause_accuracy.ci_low <= 1.0
    assert report.holdout.cause_recall.rate == 1.0
    assert report.holdout.correct_abstention_rate.numerator == 4
    assert report.holdout.correct_abstention_rate.denominator == 4
    assert report.holdout.correct_abstention_rate.rate == 1.0
    assert report.holdout.wrong_action_rate.numerator == 0
    assert report.holdout.wrong_action_rate.rate == 0.0


def test_overlapping_calibration_and_holdout_case_ids_are_rejected() -> None:
    cal_cases, cal_results = _build_scenario_cohort(("D001",), (), "shared")
    with pytest.raises(ValueError, match="MUST be disjoint"):
        evaluate_disjoint_causal_holdout(
            calibration_cases=cal_cases,
            calibration_results=cal_results,
            holdout_cases=cal_cases,
            holdout_results=cal_results,
            runner_id="runner-1",
            runner_source_revision=REV_RUNNER,
            runner_method="m1",
        )


def test_wilson_interval_bounds_and_validation() -> None:
    empty = wilson_interval(0, 0)
    assert (empty.rate, empty.ci_low, empty.ci_high) == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="wilson_interval"):
        wilson_interval(5, 4)
