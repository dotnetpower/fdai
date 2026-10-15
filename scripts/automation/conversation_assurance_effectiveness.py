"""Content-free effectiveness metrics for conversation improvement runs."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path

from fdai.core.conversation_assurance import PrivateJsonlLedger, open_private_lock
from scripts.automation.conversation_assurance_effectiveness_contract import (
    EffectivenessAssessment,
    EffectivenessPolicy,
    RemediationEvidence,
    canonical_digest,
    read_assessment,
    read_policy,
    read_remediation_evidence,
    wilson_lower_bound,
    write_remediation_evidence,
)
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


def compare_effectiveness_v2(
    *,
    baseline: ImprovementRun,
    holdout: ImprovementRun,
    baseline_assessment: EffectivenessAssessment,
    holdout_assessment: EffectivenessAssessment,
    remediation: RemediationEvidence,
    policy: EffectivenessPolicy,
    base_revision: str,
    revision_contains: RevisionContains,
) -> dict[str, object]:
    """Reduce one strict, profile-matched, base-contained effectiveness pair."""

    legacy = compare_predeclared_holdout(
        baseline=baseline,
        holdout=holdout,
        base_revision=base_revision,
        revision_contains=revision_contains,
    )
    if (
        baseline.effectiveness_schema_version != "2.0.0"
        or holdout.effectiveness_schema_version != "2.0.0"
    ):
        raise ValueError("effectiveness_pair_requires_schema_v2")
    contract_fields = (
        "cohort_id",
        "locale",
        "suite",
        "expected_primary_agent",
        "expected_routing_method",
        "t2_expectation",
        "challenge_family",
        "objective_oracle",
        "blind_holdout_receipt_digest",
        "authoritative_base_ref",
        "readiness_digest",
    )
    if any(getattr(baseline, name) != getattr(holdout, name) for name in contract_fields):
        raise ValueError("effectiveness_pair_contract_mismatch")
    if (
        baseline.cohort_id != policy.cohort_id
        or baseline.authoritative_base_ref != policy.authoritative_base_ref
    ):
        raise ValueError("effectiveness_pair_policy_mismatch")
    for assessment, run, label in (
        (baseline_assessment, baseline, "baseline"),
        (holdout_assessment, holdout, "holdout"),
    ):
        if (
            assessment.run_id != run.run_id
            or assessment.case_id != run.case_id
            or assessment.locale != run.locale
        ):
            raise ValueError(f"effectiveness_{label}_assessment_mismatch")
    if (
        baseline_assessment.rubric_version != holdout_assessment.rubric_version
        or baseline_assessment.measurement_profile_digest
        != holdout_assessment.measurement_profile_digest
        or baseline_assessment.evidence_snapshot_digest
        != holdout_assessment.evidence_snapshot_digest
        or baseline_assessment.max_score != holdout_assessment.max_score
    ):
        raise ValueError("effectiveness_measurement_profile_mismatch")
    oracle_required = baseline.objective_oracle != "none"
    if (
        baseline_assessment.objective_oracle_applicable != oracle_required
        or holdout_assessment.objective_oracle_applicable != oracle_required
    ):
        raise ValueError("effectiveness_objective_oracle_contract_mismatch")
    if not holdout_assessment.assurance_passed:
        raise ValueError("effectiveness_holdout_mandatory_gate_failed")
    if remediation.run_id != baseline.run_id:
        raise ValueError("effectiveness_remediation_run_mismatch")
    if (
        remediation.source_revision != baseline.source_revision
        or remediation.remediation_revision != baseline.remediation_revision
        or not remediation.task_owned_only
    ):
        raise ValueError("effectiveness_remediation_evidence_mismatch")

    baseline_ratio = baseline_assessment.total_score / baseline_assessment.max_score
    holdout_ratio = holdout_assessment.total_score / holdout_assessment.max_score
    ratio_delta = holdout_ratio - baseline_ratio
    outcome = "improved" if ratio_delta > 0 else "regressed" if ratio_delta < 0 else "unchanged"
    return {
        **legacy,
        "schema_version": "2.0.0",
        "pair_key": f"{baseline.comparison_group_id}:{baseline.run_id}:{holdout.run_id}",
        "cohort_id": baseline.cohort_id,
        "locale": baseline.locale,
        "policy_digest": policy.content_digest,
        "rubric_version": baseline_assessment.rubric_version,
        "measurement_profile_digest": baseline_assessment.measurement_profile_digest,
        "evidence_snapshot_digest": baseline_assessment.evidence_snapshot_digest,
        "baseline_assessment_digest": baseline_assessment.content_digest,
        "holdout_assessment_digest": holdout_assessment.content_digest,
        "remediation_evidence_digest": remediation.content_digest,
        "baseline_ratio": round(baseline_ratio, 6),
        "holdout_ratio": round(holdout_ratio, 6),
        "ratio_delta": round(ratio_delta, 6),
        "outcome": outcome,
        "hard_zero_count": holdout_assessment.hard_zero_count,
        "mandatory_gate_passed": holdout_assessment.mandatory_gate_passed,
        "objective_oracle_passed": (
            not holdout_assessment.objective_oracle_applicable
            or holdout_assessment.objective_oracle_passed
        ),
        "technical_verified": holdout_assessment.technical_verified,
        "latency_ms": holdout_assessment.latency_ms,
        "model_call_count": holdout_assessment.model_call_count,
        "cost_usd": holdout_assessment.cost_usd,
        "candidate_state": (
            "stopped"
            if outcome == "regressed"
            else "review_required"
            if outcome == "unchanged"
            else "eligible_for_cohort_only"
        ),
        "promotion_allowed": False,
        "rollback_required": outcome == "regressed",
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


def build_effectiveness_report_v2(
    *,
    runs: Sequence[ImprovementRun],
    assessments: Mapping[str, EffectivenessAssessment],
    comparisons: Sequence[Mapping[str, object]],
    policy: EffectivenessPolicy,
    base_revision: str,
    preflight_holds: Sequence[Mapping[str, object]],
    revision_contains: RevisionContains,
) -> dict[str, object]:
    """Build a deduplicated statistical cohort without granting qualification."""

    cohort_runs = tuple(
        run
        for run in runs
        if run.effectiveness_schema_version == "2.0.0"
        and run.cohort_id == policy.cohort_id
        and run.authoritative_base_ref == policy.authoritative_base_ref
    )
    legacy_runs = len(runs) - len(cohort_runs)
    categories = [outcome_category(run) for run in cohort_runs]
    measured_runs = [run for run in cohort_runs if run.measurement_attempts == 1]
    runs_by_id = {run.run_id: run for run in cohort_runs}
    unique: dict[str, Mapping[str, object]] = {}
    for item in comparisons:
        if (
            item.get("schema_version") != "2.0.0"
            or item.get("cohort_id") != policy.cohort_id
            or item.get("policy_digest") != policy.content_digest
        ):
            continue
        pair_key = item.get("pair_key")
        remediation_revision = item.get("remediation_revision")
        baseline_run_id = item.get("baseline_run_id")
        holdout_run_id = item.get("holdout_run_id")
        if not isinstance(pair_key, str) or not isinstance(remediation_revision, str):
            continue
        if (
            not isinstance(baseline_run_id, str)
            or not isinstance(holdout_run_id, str)
            or baseline_run_id not in runs_by_id
            or holdout_run_id not in runs_by_id
            or baseline_run_id not in assessments
            or holdout_run_id not in assessments
            or item.get("baseline_assessment_digest") != assessments[baseline_run_id].content_digest
            or item.get("holdout_assessment_digest") != assessments[holdout_run_id].content_digest
        ):
            continue
        if not revision_contains(remediation_revision, base_revision):
            continue
        existing = unique.get(pair_key)
        if existing is not None and canonical_digest(existing) != canonical_digest(item):
            raise ValueError("effectiveness_duplicate_pair_conflict")
        unique.setdefault(pair_key, item)
    results = tuple(unique.values())
    outcomes = tuple(str(item.get("outcome")) for item in results)
    locale_counts = {
        locale: sum(item.get("locale") == locale for item in results)
        for locale in policy.required_locales
    }
    successful = outcomes.count("improved")
    lower_bound = wilson_lower_bound(successes=successful, trials=len(results))
    environment_holds = categories.count(OutcomeCategory.ENVIRONMENT_HOLD)
    cohort_preflight_holds = [
        row for row in preflight_holds if row.get("cohort_id") == policy.cohort_id
    ]
    preflight_reasons: dict[str, int] = {}
    for row in cohort_preflight_holds:
        reason = row.get("reason")
        if isinstance(reason, str):
            preflight_reasons[reason] = preflight_reasons.get(reason, 0) + 1
    environment_trials = len(measured_runs) + len(cohort_preflight_holds)
    environment_hold_rate = (
        (environment_holds + len(cohort_preflight_holds)) / environment_trials
        if environment_trials
        else None
    )
    measured_assessments = [
        assessments[run.run_id] for run in measured_runs if run.run_id in assessments
    ]
    assessment_coverage_complete = bool(measured_runs) and (
        len(measured_assessments) == len(measured_runs)
    )
    total_latency_ms = sum(item.latency_ms for item in measured_assessments)
    total_model_calls = sum(item.model_call_count for item in measured_assessments)
    costs = [item.cost_usd for item in measured_assessments]
    cost_observation_complete = (
        bool(measured_assessments)
        and assessment_coverage_complete
        and all(value is not None for value in costs)
    )
    total_cost_usd = (
        round(sum(value for value in costs if value is not None), 6)
        if cost_observation_complete
        else None
    )
    latency_per_run = total_latency_ms / len(measured_assessments) if measured_assessments else None
    model_calls_per_run = (
        total_model_calls / len(measured_assessments) if measured_assessments else None
    )
    cost_per_run = (
        total_cost_usd / len(measured_assessments)
        if total_cost_usd is not None and measured_assessments
        else None
    )
    performance_budget_met = (
        latency_per_run is not None
        and latency_per_run <= policy.maximum_latency_ms_per_measured_run
        and model_calls_per_run is not None
        and model_calls_per_run <= policy.maximum_model_calls_per_measured_run
        and cost_per_run is not None
        and cost_per_run <= policy.maximum_cost_usd_per_measured_run
    )
    locale_floor_met = all(
        locale_counts[locale] >= policy.minimum_pairs_per_locale
        for locale in policy.required_locales
    )
    threshold_met = (
        len(results) >= policy.minimum_pairs
        and locale_floor_met
        and lower_bound is not None
        and lower_bound >= policy.minimum_improvement_rate
        and outcomes.count("regressed") <= policy.maximum_regressions
        and all(item.get("hard_zero_count") == 0 for item in results)
        and environment_hold_rate is not None
        and environment_hold_rate <= policy.maximum_environment_hold_rate
        and performance_budget_met
        and assessment_coverage_complete
    )
    return {
        "schema_version": "2.0.0",
        "policy_id": policy.policy_id,
        "policy_digest": policy.content_digest,
        "cohort_id": policy.cohort_id,
        "base_revision": base_revision,
        "runs": len(cohort_runs),
        "legacy_runs_excluded": legacy_runs,
        "measured_runs": len(measured_runs),
        "environment_holds": environment_holds,
        "evaluation_holds": categories.count(OutcomeCategory.EVALUATION_HOLD),
        "preflight_holds": len(cohort_preflight_holds),
        "preflight_reason_counts": dict(sorted(preflight_reasons.items())),
        "environment_hold_rate": (
            round(environment_hold_rate, 6) if environment_hold_rate is not None else None
        ),
        "unique_holdout_comparisons": len(results),
        "improved_holdouts": successful,
        "unchanged_holdouts": outcomes.count("unchanged"),
        "regressed_holdouts": outcomes.count("regressed"),
        "locale_pair_counts": locale_counts,
        "improvement_rate": (round(successful / len(results), 6) if results else None),
        "improvement_rate_lower_95": (round(lower_bound, 6) if lower_bound is not None else None),
        "effectiveness_threshold_met": threshold_met,
        "rollback_required": outcomes.count("regressed") > 0,
        "total_latency_ms": total_latency_ms,
        "total_model_calls": total_model_calls,
        "cost_observation_complete": cost_observation_complete,
        "assessment_coverage_complete": assessment_coverage_complete,
        "total_cost_usd": total_cost_usd,
        "performance_budget_met": performance_budget_met,
        "latency_per_measured_run_ms": (
            round(latency_per_run, 3) if latency_per_run is not None else None
        ),
        "model_calls_per_measured_run": (
            round(model_calls_per_run, 3) if model_calls_per_run is not None else None
        ),
        "cost_per_measured_run_usd": (round(cost_per_run, 6) if cost_per_run is not None else None),
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
    owning_paths: tuple[str, ...] = (),
    validation_receipt: Mapping[str, object] | None = None,
    evidence_path: Path | None = None,
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
        if current.effectiveness_schema_version == "2.0.0":
            if not owning_paths or validation_receipt is None or evidence_path is None:
                raise ValueError("remediation_evidence_required")
            if validation_receipt.get("passed") is not True:
                raise ValueError("remediation_validation_not_passed")
            if (
                validation_receipt.get("schema_version") != "1.0.0"
                or validation_receipt.get("source_revision") != current.source_revision
                or validation_receipt.get("remediation_revision") != revision
            ):
                raise ValueError("remediation_validation_receipt_mismatch")
            for name in ("commands_digest", "result_digest"):
                value = validation_receipt.get(name)
                if (
                    not isinstance(value, str)
                    or len(value.removeprefix("sha256:")) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in value.removeprefix("sha256:")
                    )
                ):
                    raise ValueError("remediation_validation_receipt_invalid")
            changed_paths = _git_changed_paths(
                project=project,
                source_revision=current.source_revision,
                remediation_revision=revision,
            )
            if any(
                not any(
                    path == root.rstrip("/") or path.startswith(f"{root.rstrip('/')}/")
                    for root in owning_paths
                )
                for path in changed_paths
            ):
                raise ValueError("remediation_contains_unrelated_paths")
            remediation_evidence = RemediationEvidence(
                schema_version="1.0.0",
                run_id=current.run_id,
                source_revision=current.source_revision,
                remediation_revision=revision,
                changed_paths_digest=canonical_digest({"paths": list(changed_paths)}),
                changed_path_count=len(changed_paths),
                validation_receipt_digest=canonical_digest(validation_receipt),
                hardening_digest=canonical_digest(
                    {"rounds": [asdict(item) for item in current.hardening_history]}
                ),
                owning_paths=owning_paths,
                task_owned_only=True,
            )
            write_remediation_evidence(evidence_path, remediation_evidence)
        attributed = current.record_remediation(revision)
        write_private_run(run_path, attributed)
        return attributed


def _git_changed_paths(
    *,
    project: Path,
    source_revision: str,
    remediation_revision: str,
) -> tuple[str, ...]:
    output = subprocess.run(  # noqa: S603 - fixed git command
        (
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            source_revision,
            remediation_revision,
        ),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    paths = tuple(sorted(line for line in output.splitlines() if line))
    if not paths:
        raise ValueError("remediation_changed_paths_unavailable")
    return paths


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
        if baseline.effectiveness_schema_version == "2.0.0" or (
            holdout.effectiveness_schema_version == "2.0.0"
        ):
            fields = (
                "effectiveness_schema_version",
                "cohort_id",
                "locale",
                "suite",
                "expected_primary_agent",
                "expected_routing_method",
                "t2_expectation",
                "challenge_family",
                "objective_oracle",
                "blind_holdout_receipt_digest",
                "authoritative_base_ref",
                "readiness_digest",
            )
            if any(getattr(baseline, name) != getattr(holdout, name) for name in fields):
                raise ValueError("effectiveness_pair_contract_mismatch")
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


def compare_and_record_v2(
    *,
    project: Path,
    baseline_path: Path,
    holdout_path: Path,
    baseline_assessment_path: Path,
    holdout_assessment_path: Path,
    remediation_path: Path,
    policy_path: Path,
    ledger_path: Path,
) -> dict[str, object]:
    policy = read_policy(policy_path)
    baseline = read_private_run(baseline_path)
    holdout = read_private_run(holdout_path)
    base_revision = git_revision(project, policy.authoritative_base_ref)
    result = compare_effectiveness_v2(
        baseline=baseline,
        holdout=holdout,
        baseline_assessment=read_assessment(baseline_assessment_path),
        holdout_assessment=read_assessment(holdout_assessment_path),
        remediation=read_remediation_evidence(remediation_path),
        policy=policy,
        base_revision=base_revision,
        revision_contains=lambda ancestor, descendant: git_revision_contains(
            project, ancestor, descendant
        ),
    )
    ledger = PrivateJsonlLedger(ledger_path)
    prior = ledger.read(limit=10_000)
    prior_match = next(
        (item for item in prior if item.get("pair_key") == result["pair_key"]),
        None,
    )
    if prior_match is not None:
        immutable_fields = (
            "policy_digest",
            "baseline_assessment_digest",
            "holdout_assessment_digest",
            "remediation_evidence_digest",
            "outcome",
        )
        if any(prior_match.get(name) != result.get(name) for name in immutable_fields):
            raise ValueError("effectiveness_duplicate_pair_conflict")
    duplicate = prior_match is not None
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


def effectiveness_report_v2(
    *,
    project: Path,
    runs_root: Path,
    assessments_root: Path,
    ledger_path: Path,
    policy_path: Path,
    preflight_holds_path: Path,
) -> dict[str, object]:
    policy = read_policy(policy_path)
    base_revision = git_revision(project, policy.authoritative_base_ref)
    runs = (
        tuple(
            read_private_run(path)
            for path in sorted(runs_root.glob("*.json"))
            if not path.name.endswith(".browser.json")
        )
        if runs_root.exists()
        else ()
    )
    assessments = (
        {
            assessment.run_id: assessment
            for assessment in (
                read_assessment(path) for path in sorted(assessments_root.glob("*.json"))
            )
        }
        if assessments_root.exists()
        else {}
    )
    return build_effectiveness_report_v2(
        runs=runs,
        assessments=assessments,
        comparisons=PrivateJsonlLedger(ledger_path).read(limit=10_000),
        policy=policy,
        base_revision=base_revision,
        preflight_holds=PrivateJsonlLedger(preflight_holds_path).read(limit=10_000),
        revision_contains=lambda ancestor, descendant: git_revision_contains(
            project, ancestor, descendant
        ),
    )


__all__ = [
    "OutcomeCategory",
    "attribute_remediation",
    "bind_holdout_revision",
    "build_effectiveness_report",
    "build_effectiveness_report_v2",
    "compare_and_record",
    "compare_and_record_v2",
    "compare_effectiveness_v2",
    "compare_predeclared_holdout",
    "effectiveness_report",
    "effectiveness_report_v2",
    "git_revision",
    "git_revision_contains",
    "outcome_category",
]
