"""Content-free effectiveness metrics for conversation improvement runs."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from fdai.core.conversation_assurance import PrivateJsonlLedger, open_private_lock
from scripts.automation.conversation_assurance_harness import (
    ComparisonRole,
    FailureClass,
    ImprovementRun,
    ImprovementState,
    read_private_run,
    write_private_run,
)

RevisionContains = Callable[[str, str], bool]


class OutcomeCategory(StrEnum):
    PASSED = "passed"
    QUALITY_DEFECT = "quality_defect"
    ENVIRONMENT_HOLD = "environment_hold"
    EVALUATION_HOLD = "evaluation_hold"
    UNMEASURED = "unmeasured"


_ENVIRONMENT_FAILURES = frozenset(
    {
        FailureClass.PROVIDER_OR_EVIDENCE_UNAVAILABLE,
        FailureClass.AUTHORIZATION_OR_CONFIGURATION,
        FailureClass.BASELINE_FAILURE,
    }
)


def outcome_category(run: ImprovementRun) -> OutcomeCategory:
    """Separate answer quality from prerequisites and evaluator integrity."""

    if run.measurement_attempts == 0:
        return OutcomeCategory.UNMEASURED
    if run.failure_class is None and run.state is ImprovementState.COMPLETED:
        return OutcomeCategory.PASSED
    if run.failure_class is FailureClass.CODE_DEFECT:
        return OutcomeCategory.QUALITY_DEFECT
    if run.failure_class in _ENVIRONMENT_FAILURES:
        return OutcomeCategory.ENVIRONMENT_HOLD
    return OutcomeCategory.EVALUATION_HOLD


def compare_predeclared_holdout(
    *,
    baseline: ImprovementRun,
    holdout: ImprovementRun,
    base_revision: str,
    revision_contains: RevisionContains,
) -> dict[str, object]:
    """Compare a predeclared holdout only after its remediation is in the base."""

    if baseline.run_id == holdout.run_id or baseline.case_id == holdout.case_id:
        raise ValueError("effectiveness_comparison_requires_distinct_runs")
    if baseline.question_fingerprint == holdout.question_fingerprint:
        raise ValueError("effectiveness_comparison_requires_distinct_questions")
    if (
        baseline.comparison_group_id is None
        or baseline.comparison_group_id != holdout.comparison_group_id
        or baseline.comparison_role is not ComparisonRole.BASELINE
        or holdout.comparison_role is not ComparisonRole.HOLDOUT
    ):
        raise ValueError("effectiveness_comparison_not_predeclared")
    if (
        baseline.capability_id != holdout.capability_id
        or baseline.required_functions != holdout.required_functions
        or baseline.expected_authority != holdout.expected_authority
    ):
        raise ValueError("effectiveness_comparison_contract_mismatch")
    if (
        baseline.failure_class is not FailureClass.CODE_DEFECT
        or baseline.remediation_revision is None
    ):
        raise ValueError("effectiveness_baseline_has_no_attributed_remediation")
    if outcome_category(holdout) is not OutcomeCategory.PASSED:
        raise ValueError("effectiveness_holdout_not_passed")
    if baseline.score is None or holdout.score is None:
        raise ValueError("effectiveness_comparison_unscorable")
    if baseline.source_revision != holdout.source_revision:
        raise ValueError("effectiveness_holdout_not_predeclared_with_baseline")
    if holdout.measurement_revision is None:
        raise ValueError("effectiveness_holdout_revision_not_bound")
    if not revision_contains(baseline.remediation_revision, holdout.measurement_source_revision):
        raise ValueError("effectiveness_holdout_missing_remediation")
    if not revision_contains(baseline.remediation_revision, base_revision):
        raise ValueError("effectiveness_remediation_not_in_base")

    score_delta = holdout.score - baseline.score
    outcome = "improved" if score_delta > 0 else "regressed" if score_delta < 0 else "unchanged"
    return {
        "schema_version": "1.0.0",
        "comparison_group_id": baseline.comparison_group_id,
        "baseline_run_id": baseline.run_id,
        "holdout_run_id": holdout.run_id,
        "baseline_revision": baseline.source_revision,
        "remediation_revision": baseline.remediation_revision,
        "holdout_declared_revision": holdout.source_revision,
        "holdout_revision": holdout.measurement_source_revision,
        "base_revision": base_revision,
        "baseline_score": baseline.score,
        "holdout_score": holdout.score,
        "score_delta": score_delta,
        "outcome": outcome,
        "qualification_authority": False,
        "execution_authority": False,
    }


def build_effectiveness_report(
    *,
    runs: Sequence[ImprovementRun],
    comparisons: Sequence[Mapping[str, object]],
    base_revision: str,
    revision_contains: RevisionContains,
) -> dict[str, object]:
    """Build aggregate KPIs without treating environment failures as answer failures."""

    categories = [outcome_category(run) for run in runs]
    passed = categories.count(OutcomeCategory.PASSED)
    quality_defects = categories.count(OutcomeCategory.QUALITY_DEFECT)
    quality_measurements = passed + quality_defects
    measured = sum(run.measurement_attempts for run in runs)
    attributed = [run for run in runs if run.remediation_revision is not None]
    integrated = [
        run
        for run in attributed
        if run.remediation_revision is not None
        and revision_contains(run.remediation_revision, base_revision)
    ]
    comparison_outcomes: list[str] = []
    for item in comparisons:
        recorded_base = item.get("base_revision")
        if not isinstance(recorded_base, str):
            continue
        if recorded_base == base_revision or revision_contains(recorded_base, base_revision):
            comparison_outcomes.append(str(item.get("outcome")))
    return {
        "schema_version": "1.0.0",
        "base_revision": base_revision,
        "runs": len(runs),
        "eligible_runs": sum(run.state is not ImprovementState.PREPARED for run in runs),
        "measured_runs": measured,
        "passed_quality_measurements": passed,
        "quality_defects": quality_defects,
        "quality_measurements": quality_measurements,
        "assurance_pass_rate": (
            round(passed / quality_measurements, 4) if quality_measurements else None
        ),
        "environment_holds": categories.count(OutcomeCategory.ENVIRONMENT_HOLD),
        "evaluation_holds": categories.count(OutcomeCategory.EVALUATION_HOLD),
        "unmeasured_runs": categories.count(OutcomeCategory.UNMEASURED),
        "attributed_remediations": len(attributed),
        "integrated_remediations": len(integrated),
        "holdout_comparisons": len(comparison_outcomes),
        "improved_holdouts": comparison_outcomes.count("improved"),
        "unchanged_holdouts": comparison_outcomes.count("unchanged"),
        "regressed_holdouts": comparison_outcomes.count("regressed"),
        "qualification_authority": False,
        "execution_authority": False,
    }


def git_revision(project: Path, ref: str) -> str:
    return subprocess.run(  # noqa: S603 - git receives an argument vector without a shell
        ("git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_revision_contains(project: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(  # noqa: S603 - fixed git command
        ("git", "merge-base", "--is-ancestor", ancestor, descendant),
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise ValueError("git_revision_relationship_unavailable")
    return result.returncode == 0


def attribute_remediation(
    *,
    project: Path,
    run_path: Path,
    lock_path: Path,
    revision: str,
    worktree_dirty: bool,
) -> ImprovementRun:
    if worktree_dirty:
        raise ValueError("worktree_not_clean")
    lock = open_private_lock(lock_path)
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        current = read_private_run(run_path)
        if not git_revision_contains(project, current.source_revision, revision):
            raise ValueError("remediation_revision_not_descended_from_measurement")
        attributed = current.record_remediation(revision)
        write_private_run(run_path, attributed)
        return attributed


def bind_holdout_revision(
    *,
    project: Path,
    baseline_path: Path,
    holdout_path: Path,
    holdout_lock_path: Path,
    revision: str,
    worktree_dirty: bool,
) -> ImprovementRun:
    if worktree_dirty:
        raise ValueError("worktree_not_clean")
    baseline = read_private_run(baseline_path)
    lock = open_private_lock(holdout_lock_path)
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        holdout = read_private_run(holdout_path)
        if (
            baseline.comparison_role is not ComparisonRole.BASELINE
            or holdout.comparison_role is not ComparisonRole.HOLDOUT
            or baseline.comparison_group_id is None
            or baseline.comparison_group_id != holdout.comparison_group_id
        ):
            raise ValueError("effectiveness_comparison_not_predeclared")
        if baseline.source_revision != holdout.source_revision:
            raise ValueError("effectiveness_holdout_not_predeclared_with_baseline")
        if (
            baseline.case_id == holdout.case_id
            or baseline.question_fingerprint == holdout.question_fingerprint
        ):
            raise ValueError("effectiveness_comparison_requires_distinct_questions")
        if (
            baseline.capability_id != holdout.capability_id
            or baseline.required_functions != holdout.required_functions
            or baseline.expected_authority != holdout.expected_authority
        ):
            raise ValueError("effectiveness_comparison_contract_mismatch")
        if baseline.remediation_revision != revision:
            raise ValueError("holdout_revision_must_match_attributed_remediation")
        if not git_revision_contains(project, baseline.source_revision, revision):
            raise ValueError("remediation_revision_not_descended_from_measurement")
        rebound = holdout.bind_holdout_revision(revision)
        write_private_run(holdout_path, rebound)
        return rebound


def compare_and_record(
    *,
    project: Path,
    baseline_path: Path,
    holdout_path: Path,
    ledger_path: Path,
    base_ref: str,
) -> dict[str, object]:
    baseline = read_private_run(baseline_path)
    holdout = read_private_run(holdout_path)
    base_revision = git_revision(project, base_ref)
    result = compare_predeclared_holdout(
        baseline=baseline,
        holdout=holdout,
        base_revision=base_revision,
        revision_contains=lambda ancestor, descendant: git_revision_contains(
            project, ancestor, descendant
        ),
    )
    ledger = PrivateJsonlLedger(ledger_path)
    prior = ledger.read(limit=10_000)
    duplicate = any(
        item.get("baseline_run_id") == baseline.run_id
        and item.get("holdout_run_id") == holdout.run_id
        and item.get("base_revision") == base_revision
        for item in prior
    )
    if not duplicate:
        ledger.append(result)
    return {**result, "duplicate": duplicate}


def effectiveness_report(
    *,
    project: Path,
    runs_root: Path,
    ledger_path: Path,
    base_ref: str,
) -> dict[str, object]:
    base_revision = git_revision(project, base_ref)
    runs = (
        tuple(
            read_private_run(path)
            for path in sorted(runs_root.glob("*.json"))
            if not path.name.endswith(".browser.json")
        )
        if runs_root.exists()
        else ()
    )
    comparisons = PrivateJsonlLedger(ledger_path).read(limit=10_000)
    return build_effectiveness_report(
        runs=runs,
        comparisons=comparisons,
        base_revision=base_revision,
        revision_contains=lambda ancestor, descendant: git_revision_contains(
            project, ancestor, descendant
        ),
    )


__all__ = [
    "OutcomeCategory",
    "attribute_remediation",
    "bind_holdout_revision",
    "build_effectiveness_report",
    "compare_and_record",
    "compare_predeclared_holdout",
    "effectiveness_report",
    "git_revision",
    "git_revision_contains",
    "outcome_category",
]
