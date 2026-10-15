from __future__ import annotations

from pathlib import Path

import pytest
import scripts.automation.conversation_assurance_effectiveness as effectiveness
from scripts.automation.conversation_assurance_effectiveness import (
    OutcomeCategory,
    build_effectiveness_report,
    compare_predeclared_holdout,
    outcome_category,
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
    monkeypatch.setattr(effectiveness, "git_revision_contains", lambda *_args: True)

    rebound = effectiveness.bind_holdout_revision(
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
    monkeypatch.setattr(effectiveness, "git_revision", lambda *_args: "4" * 40)
    monkeypatch.setattr(effectiveness, "git_revision_contains", lambda *_args: True)

    report = effectiveness.effectiveness_report(
        project=tmp_path,
        runs_root=runs_root,
        ledger_path=tmp_path / "comparisons.jsonl",
        base_ref="HEAD",
    )

    assert report["runs"] == 1
    assert report["passed_quality_measurements"] == 1
