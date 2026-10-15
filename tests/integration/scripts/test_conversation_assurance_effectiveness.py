from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest
import scripts.automation.conversation_assurance_effectiveness_io as effectiveness_io
from scripts.automation.conversation_assurance_effectiveness import (
    OutcomeCategory,
    build_effectiveness_report,
    build_effectiveness_report_v2,
    compare_effectiveness_v2,
    compare_predeclared_holdout,
    outcome_category,
)
from scripts.automation.conversation_assurance_effectiveness_contract import (
    EffectivenessAssessment,
    EffectivenessPolicy,
    RemediationEvidence,
    canonical_digest,
    read_remediation_evidence,
)
from scripts.automation.conversation_assurance_harness import (
    ComparisonRole,
    FailureClass,
    FindingSeverity,
    GateState,
    ImprovementRun,
    MeasurementOutcome,
    PresentationGate,
    read_private_run,
    write_private_run,
)


def _measured_run(
    *,
    run_id: str,
    case_id: str,
    fingerprint: str,
    source_revision: str,
    role: ComparisonRole,
    score: int,
    verdict: str,
    failure_class: FailureClass | None,
    measurement_revision: str | None = None,
) -> ImprovementRun:
    run = ImprovementRun(
        run_id=run_id,
        case_id=case_id,
        question_fingerprint=f"sha256:{fingerprint * 64}",
        source_revision=source_revision,
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure-resource-graph",
        provided_authority="azure-resource-graph",
        comparison_group_id="resource-state-fix-one",
        comparison_role=role,
    ).validate_dry_run(
        question_count=1,
        child_count=1,
        corpus_digest="d" * 64,
    )
    if measurement_revision is not None:
        run = run.bind_holdout_revision(measurement_revision)
    run = (
        run.record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=score,
                verdict=verdict,
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.PASSED),
        )
        .classify(failure_class)
    )
    if failure_class is FailureClass.CODE_DEFECT:
        for index in range(10):
            run = run.record_hardening_round(
                FindingSeverity.NONE,
                reviewer_scope=f"review-{index + 1}",
            )
    return run


def _v2_run(
    *,
    role: ComparisonRole,
    run_id: str,
    case_id: str,
    fingerprint: str,
    score: int,
    verdict: str,
    failure_class: FailureClass | None,
    measurement_revision: str | None = None,
) -> ImprovementRun:
    return replace(
        _measured_run(
            run_id=run_id,
            case_id=case_id,
            fingerprint=fingerprint,
            source_revision="1" * 40,
            role=role,
            score=score,
            verdict=verdict,
            failure_class=failure_class,
            measurement_revision=measurement_revision,
        ),
        effectiveness_schema_version="2.0.0",
        effectiveness_policy_digest=_policy().content_digest,
        cohort_id="cohort-one",
        locale="en",
        suite="external",
        expected_primary_agent="heimdall",
        expected_routing_method="semantic_judgment",
        t2_expectation="forbidden",
        challenge_family="resource-state",
        objective_oracle="resource-state-oracle",
        blind_holdout_receipt_digest="sha256:" + "c" * 64,
        authoritative_base_ref="main",
        readiness_digest="sha256:" + "d" * 64,
    )


def _policy() -> EffectivenessPolicy:
    return EffectivenessPolicy(
        schema_version="1.0.0",
        policy_id="effectiveness-policy-one",
        cohort_id="cohort-one",
        authoritative_base_ref="main",
        required_locales=("en", "ko"),
        minimum_pairs=20,
        minimum_pairs_per_locale=10,
        minimum_improvement_rate=0.8,
        minimum_pair_ratio_delta=0.1,
        confidence_level=0.95,
        maximum_regressions=0,
        maximum_environment_hold_rate=0.1,
        maximum_latency_ms_per_measured_run=120_000,
        maximum_model_calls_per_measured_run=10.0,
        maximum_cost_usd_per_measured_run=1.0,
    )


def _assessment(
    run: ImprovementRun,
    *,
    score: int,
    mandatory: bool,
) -> EffectivenessAssessment:
    failed_rubrics = (
        "appropriateness",
        "completeness",
        "grounding",
        "authority_safety",
        "visualization",
        "investigation_detail",
        "execution_detail",
        "performance",
        "response_integrity",
        "verification",
    )[: 10 - score]
    mandatory_failures = tuple(
        value
        for value in failed_rubrics
        if value
        in {
            "appropriateness",
            "completeness",
            "grounding",
            "verification",
            "authority_safety",
            "response_integrity",
        }
    )
    if not mandatory:
        mandatory_failures = (*mandatory_failures, "objective_oracle")
    return EffectivenessAssessment(
        schema_version="1.0.0",
        run_id=run.run_id,
        case_id=run.case_id,
        question_fingerprint=run.question_fingerprint,
        measurement_revision=run.measurement_source_revision,
        trace_receipt_digest="sha256:" + "9" * 64,
        locale=run.locale or "en",
        rubric_version="conversation-assurance.v2",
        measurement_profile_digest="sha256:" + "e" * 64,
        evidence_snapshot_digest="sha256:" + "f" * 64,
        total_score=score,
        max_score=10,
        mandatory_gate_passed=mandatory,
        objective_oracle_applicable=True,
        objective_oracle_passed=mandatory,
        hard_zero_count=0,
        technical_verified="verification" not in mandatory_failures,
        failed_rubrics=failed_rubrics,
        mandatory_gate_failures=mandatory_failures,
        latency_ms=1000,
        model_call_count=3,
        cost_usd=0.01,
    )


def test_predeclared_holdout_requires_integrated_remediation() -> None:
    baseline = _measured_run(
        run_id="baseline-one",
        case_id="baseline-case",
        fingerprint="a",
        source_revision="1" * 40,
        role=ComparisonRole.BASELINE,
        score=20,
        verdict="fail",
        failure_class=FailureClass.CODE_DEFECT,
    ).record_remediation("2" * 40)
    holdout = _measured_run(
        run_id="holdout-one",
        case_id="holdout-case",
        fingerprint="b",
        source_revision="1" * 40,
        role=ComparisonRole.HOLDOUT,
        score=29,
        verdict="pass",
        failure_class=None,
        measurement_revision="2" * 40,
    )
    ancestry = {
        ("2" * 40, "2" * 40),
        ("2" * 40, "4" * 40),
    }

    result = compare_predeclared_holdout(
        baseline=baseline,
        holdout=holdout,
        base_revision="4" * 40,
        revision_contains=lambda ancestor, descendant: (ancestor, descendant) in ancestry,
    )

    assert result["outcome"] == "improved"
    assert result["score_delta"] == 9
    assert result["qualification_authority"] is False


def test_holdout_rejects_remediation_not_contained_in_base() -> None:
    baseline = _measured_run(
        run_id="baseline-one",
        case_id="baseline-case",
        fingerprint="a",
        source_revision="1" * 40,
        role=ComparisonRole.BASELINE,
        score=20,
        verdict="fail",
        failure_class=FailureClass.CODE_DEFECT,
    ).record_remediation("2" * 40)
    holdout = _measured_run(
        run_id="holdout-one",
        case_id="holdout-case",
        fingerprint="b",
        source_revision="1" * 40,
        role=ComparisonRole.HOLDOUT,
        score=29,
        verdict="pass",
        failure_class=None,
        measurement_revision="2" * 40,
    )

    with pytest.raises(ValueError, match="remediation_not_in_base"):
        compare_predeclared_holdout(
            baseline=baseline,
            holdout=holdout,
            base_revision="4" * 40,
            revision_contains=lambda ancestor, descendant: descendant == "2" * 40,
        )


def test_bind_holdout_revision_preserves_predeclared_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path
    baseline_path = project / "baseline.json"
    holdout_path = project / "holdout.json"
    lock_path = project / "holdout.lock"
    baseline = _measured_run(
        run_id="baseline-one",
        case_id="baseline-case",
        fingerprint="a",
        source_revision="1" * 40,
        role=ComparisonRole.BASELINE,
        score=20,
        verdict="fail",
        failure_class=FailureClass.CODE_DEFECT,
    ).record_remediation("2" * 40)
    holdout = ImprovementRun(
        run_id="holdout-one",
        case_id="holdout-case",
        question_fingerprint="sha256:" + "b" * 64,
        source_revision="1" * 40,
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure-resource-graph",
        provided_authority="azure-resource-graph",
        comparison_group_id="resource-state-fix-one",
        comparison_role=ComparisonRole.HOLDOUT,
    ).validate_dry_run(
        question_count=1,
        child_count=1,
        corpus_digest="e" * 64,
    )
    write_private_run(baseline_path, baseline)
    write_private_run(holdout_path, holdout)
    monkeypatch.setattr(effectiveness_io, "git_revision_contains", lambda *_args: True)

    rebound = effectiveness_io.bind_holdout_revision(
        project=project,
        baseline_path=baseline_path,
        holdout_path=holdout_path,
        holdout_lock_path=lock_path,
        revision="2" * 40,
        worktree_dirty=False,
    )

    assert rebound.source_revision == "1" * 40
    assert rebound.measurement_source_revision == "2" * 40
    assert read_private_run(holdout_path) == rebound


def test_v2_remediation_records_task_owned_diff_and_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_path = tmp_path / "baseline.json"
    evidence_path = tmp_path / "remediation.json"
    baseline = _v2_run(
        role=ComparisonRole.BASELINE,
        run_id="baseline-v2",
        case_id="baseline-case-v2",
        fingerprint="a",
        score=20,
        verdict="fail",
        failure_class=FailureClass.CODE_DEFECT,
    )
    write_private_run(run_path, baseline)
    monkeypatch.setattr(effectiveness_io, "git_revision_contains", lambda *_args: True)
    monkeypatch.setattr(
        effectiveness_io,
        "_git_changed_paths",
        lambda **_kwargs: ("scripts/automation/example.py",),
    )

    attributed = effectiveness_io.attribute_remediation(
        project=tmp_path,
        run_path=run_path,
        lock_path=tmp_path / "baseline.lock",
        revision="2" * 40,
        worktree_dirty=False,
        owning_paths=("scripts/automation",),
        validation_receipt={
            "schema_version": "1.0.0",
            "passed": True,
            "source_revision": baseline.source_revision,
            "remediation_revision": "2" * 40,
            "commands_digest": "sha256:" + "1" * 64,
            "result_digest": "sha256:" + "2" * 64,
        },
        evidence_path=evidence_path,
    )

    evidence = read_remediation_evidence(evidence_path)
    assert attributed.remediation_revision == "2" * 40
    assert evidence.changed_path_count == 1
    assert evidence.task_owned_only is True

    repeated = effectiveness_io.attribute_remediation(
        project=tmp_path,
        run_path=run_path,
        lock_path=tmp_path / "baseline.lock",
        revision="2" * 40,
        worktree_dirty=False,
        owning_paths=("scripts/automation",),
        validation_receipt={
            "schema_version": "1.0.0",
            "passed": True,
            "source_revision": baseline.source_revision,
            "remediation_revision": "2" * 40,
            "commands_digest": "sha256:" + "1" * 64,
            "result_digest": "sha256:" + "2" * 64,
        },
        evidence_path=evidence_path,
    )
    assert repeated == attributed


def test_effectiveness_report_separates_environment_from_quality() -> None:
    defect = _measured_run(
        run_id="baseline-one",
        case_id="baseline-case",
        fingerprint="a",
        source_revision="1" * 40,
        role=ComparisonRole.BASELINE,
        score=20,
        verdict="fail",
        failure_class=FailureClass.CODE_DEFECT,
    ).record_remediation("2" * 40)
    passed = _measured_run(
        run_id="holdout-one",
        case_id="holdout-case",
        fingerprint="b",
        source_revision="3" * 40,
        role=ComparisonRole.HOLDOUT,
        score=29,
        verdict="pass",
        failure_class=None,
    )
    unavailable = (
        ImprovementRun(
            run_id="environment-one",
            case_id="environment-case",
            question_fingerprint="sha256:" + "c" * 64,
            source_revision="1" * 40,
            capability_id="current-resource-state",
            required_functions=("query.resource_state_inventory",),
            expected_authority="azure-resource-graph",
            provided_authority="azure-resource-graph",
        )
        .validate_dry_run(
            question_count=1,
            child_count=1,
            corpus_digest="e" * 64,
        )
        .record_measurement(
            MeasurementOutcome(
                terminal_state="held",
                answer_generation_state="unavailable",
                assessment_state="unavailable",
                assessment_reasons=("provider_unavailable",),
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.HELD, ("provider_unavailable",)),
            prompt_assembly=PresentationGate(GateState.HELD, ("provider_unavailable",)),
            preparing_answer=PresentationGate(GateState.HELD, ("provider_unavailable",)),
        )
        .classify(FailureClass.PROVIDER_OR_EVIDENCE_UNAVAILABLE)
    )

    report = build_effectiveness_report(
        runs=(defect, passed, unavailable),
        comparisons=(
            {
                "base_revision": "4" * 40,
                "outcome": "improved",
                "ratio_delta": 0.4,
            },
        ),
        base_revision="4" * 40,
        revision_contains=lambda ancestor, descendant: (
            ancestor == "2" * 40 and descendant == "4" * 40
        ),
    )

    assert outcome_category(unavailable) is OutcomeCategory.ENVIRONMENT_HOLD
    assert report["quality_measurements"] == 2
    assert report["assurance_pass_rate"] == 0.5
    assert report["environment_holds"] == 1
    assert report["integrated_remediations"] == 1
    assert report["improved_holdouts"] == 1


def test_effectiveness_report_ignores_browser_evidence_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "runs"
    run = _measured_run(
        run_id="holdout-one",
        case_id="holdout-case",
        fingerprint="b",
        source_revision="1" * 40,
        role=ComparisonRole.HOLDOUT,
        score=29,
        verdict="pass",
        failure_class=None,
    )
    write_private_run(runs_root / "holdout-one.json", run)
    (runs_root / "holdout-one.browser.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(effectiveness_io, "git_revision", lambda *_args: "4" * 40)
    monkeypatch.setattr(effectiveness_io, "git_revision_contains", lambda *_args: True)

    report = effectiveness_io.effectiveness_report(
        project=tmp_path,
        runs_root=runs_root,
        ledger_path=tmp_path / "comparisons.jsonl",
        base_ref="HEAD",
    )

    assert report["runs"] == 1
    assert report["passed_quality_measurements"] == 1


def test_v2_comparison_requires_mandatory_gates_and_task_owned_remediation() -> None:
    baseline = _v2_run(
        role=ComparisonRole.BASELINE,
        run_id="baseline-v2",
        case_id="baseline-case-v2",
        fingerprint="1",
        score=20,
        verdict="fail",
        failure_class=FailureClass.CODE_DEFECT,
    ).record_remediation("2" * 40)
    holdout = _v2_run(
        role=ComparisonRole.HOLDOUT,
        run_id="holdout-v2",
        case_id="holdout-case-v2",
        fingerprint="2",
        score=30,
        verdict="pass",
        failure_class=None,
        measurement_revision="2" * 40,
    )
    remediation = RemediationEvidence(
        schema_version="1.0.0",
        run_id=baseline.run_id,
        source_revision=baseline.source_revision,
        remediation_revision="2" * 40,
        changed_paths_digest="sha256:" + "3" * 64,
        changed_path_count=1,
        validation_receipt_digest="sha256:" + "4" * 64,
        hardening_digest=canonical_digest(
            {"rounds": [asdict(item) for item in baseline.hardening_history]}
        ),
        owning_paths=("scripts/automation",),
        task_owned_only=True,
    )

    result = compare_effectiveness_v2(
        baseline=baseline,
        holdout=holdout,
        baseline_assessment=_assessment(baseline, score=6, mandatory=False),
        holdout_assessment=_assessment(holdout, score=10, mandatory=True),
        remediation=remediation,
        policy=_policy(),
        base_revision="6" * 40,
        revision_contains=lambda ancestor, descendant: (
            ancestor == "2" * 40 and descendant in {"2" * 40, "6" * 40}
        ),
    )

    assert result["outcome"] == "improved"
    assert result["mandatory_gate_passed"] is True
    assert result["promotion_allowed"] is False
    assert result["candidate_state"] == "eligible_for_cohort_only"

    with pytest.raises(ValueError, match="mandatory_gate_failed"):
        compare_effectiveness_v2(
            baseline=baseline,
            holdout=holdout,
            baseline_assessment=_assessment(baseline, score=6, mandatory=False),
            holdout_assessment=_assessment(holdout, score=9, mandatory=False),
            remediation=remediation,
            policy=_policy(),
            base_revision="6" * 40,
            revision_contains=lambda *_args: True,
        )
    with pytest.raises(ValueError, match="baseline_did_not_fail"):
        compare_effectiveness_v2(
            baseline=baseline,
            holdout=holdout,
            baseline_assessment=_assessment(baseline, score=10, mandatory=True),
            holdout_assessment=_assessment(holdout, score=10, mandatory=True),
            remediation=remediation,
            policy=_policy(),
            base_revision="6" * 40,
            revision_contains=lambda *_args: True,
        )
    with pytest.raises(ValueError, match="remediation_evidence_mismatch"):
        changed_holdout = replace(holdout, measurement_revision="3" * 40)
        compare_effectiveness_v2(
            baseline=baseline,
            holdout=changed_holdout,
            baseline_assessment=_assessment(baseline, score=6, mandatory=False),
            holdout_assessment=_assessment(changed_holdout, score=10, mandatory=True),
            remediation=remediation,
            policy=_policy(),
            base_revision="6" * 40,
            revision_contains=lambda *_args: True,
        )


def test_v2_report_deduplicates_pairs_and_applies_statistical_floor() -> None:
    policy = _policy()
    comparisons: list[dict[str, object]] = []
    runs: list[ImprovementRun] = []
    assessments: dict[str, EffectivenessAssessment] = {}
    for index in range(20):
        locale = "en" if index < 10 else "ko"
        baseline = replace(
            _v2_run(
                role=ComparisonRole.BASELINE,
                run_id=f"baseline-{index}",
                case_id=f"baseline-case-{index}",
                fingerprint="a",
                score=20,
                verdict="fail",
                failure_class=FailureClass.CODE_DEFECT,
            ).record_remediation("2" * 40),
            locale=locale,
        )
        holdout = replace(
            _v2_run(
                role=ComparisonRole.HOLDOUT,
                run_id=f"holdout-{index}",
                case_id=f"holdout-case-{index}",
                fingerprint="b",
                score=30,
                verdict="pass",
                failure_class=None,
                measurement_revision="2" * 40,
            ),
            locale=locale,
        )
        runs.extend((baseline, holdout))
        assessments[baseline.run_id] = _assessment(baseline, score=6, mandatory=False)
        assessments[holdout.run_id] = _assessment(holdout, score=10, mandatory=True)
        row = {
            "schema_version": "2.0.0",
            "cohort_id": policy.cohort_id,
            "policy_digest": policy.content_digest,
            "pair_key": canonical_digest(
                {
                    "comparison_group_id": baseline.comparison_group_id,
                    "baseline_run_id": baseline.run_id,
                    "holdout_run_id": holdout.run_id,
                }
            ),
            "baseline_run_id": baseline.run_id,
            "holdout_run_id": holdout.run_id,
            "baseline_assessment_digest": assessments[baseline.run_id].content_digest,
            "holdout_assessment_digest": assessments[holdout.run_id].content_digest,
            "remediation_evidence_digest": "sha256:" + "7" * 64,
            "remediation_revision": "2" * 40,
            "locale": locale,
            "outcome": "improved",
            "ratio_delta": 0.4,
            "hard_zero_count": 0,
            "mandatory_gate_passed": True,
            "objective_oracle_passed": True,
            "technical_verified": True,
            "candidate_state": "eligible_for_cohort_only",
        }
        comparisons.extend((row, dict(row)))

    report = build_effectiveness_report_v2(
        runs=runs,
        assessments=assessments,
        comparisons=comparisons,
        policy=policy,
        base_revision="3" * 40,
        preflight_holds=(
            {
                "cohort_id": "other-cohort",
                "reason": "evidence_snapshot_unavailable",
            },
        ),
        revision_contains=lambda ancestor, descendant: (
            ancestor == "2" * 40 and descendant == "3" * 40
        ),
    )

    assert report["unique_holdout_comparisons"] == 20
    assert report["locale_pair_counts"] == {"en": 10, "ko": 10}
    assert report["improvement_rate"] == 1.0
    assert report["improvement_rate_lower_95"] > 0.8
    assert report["environment_hold_rate"] == 0.0
    assert report["preflight_holds"] == 0
    assert report["cost_observation_complete"] is True
    assert report["performance_budget_met"] is True
    assert report["effectiveness_threshold_met"] is True

    conflicting = dict(comparisons[0])
    conflicting["remediation_evidence_digest"] = "sha256:" + "8" * 64
    with pytest.raises(ValueError, match="duplicate_pair_conflict"):
        build_effectiveness_report_v2(
            runs=runs,
            assessments=assessments,
            comparisons=(*comparisons, conflicting),
            policy=policy,
            base_revision="3" * 40,
            preflight_holds=(),
            revision_contains=lambda *_args: True,
        )

    reused = dict(comparisons[0])
    reused_holdout = runs[3]
    reused["holdout_run_id"] = reused_holdout.run_id
    reused["holdout_assessment_digest"] = assessments[reused_holdout.run_id].content_digest
    reused["pair_key"] = canonical_digest(
        {
            "comparison_group_id": runs[0].comparison_group_id,
            "baseline_run_id": runs[0].run_id,
            "holdout_run_id": reused_holdout.run_id,
        }
    )
    with pytest.raises(ValueError, match="run_reused"):
        build_effectiveness_report_v2(
            runs=runs,
            assessments=assessments,
            comparisons=(*comparisons, reused),
            policy=policy,
            base_revision="3" * 40,
            preflight_holds=(),
            revision_contains=lambda *_args: True,
        )

    slow_assessments = dict(assessments)
    first_run_id = next(iter(slow_assessments))
    slow_assessments[first_run_id] = replace(
        slow_assessments[first_run_id],
        latency_ms=policy.maximum_latency_ms_per_measured_run + 1,
    )
    slow_comparisons = [
        {
            **item,
            "baseline_assessment_digest": slow_assessments[first_run_id].content_digest,
        }
        if item["baseline_run_id"] == first_run_id
        else item
        for item in comparisons
    ]
    slow = build_effectiveness_report_v2(
        runs=runs,
        assessments=slow_assessments,
        comparisons=slow_comparisons,
        policy=policy,
        base_revision="3" * 40,
        preflight_holds=(),
        revision_contains=lambda *_args: True,
    )
    assert slow["performance_budget_met"] is False
    assert slow["effectiveness_threshold_met"] is False
