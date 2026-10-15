"""Git and owner-only persistence for conversation effectiveness."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from fdai.core.conversation_assurance import PrivateJsonlLedger, open_private_lock
from scripts.automation.conversation_assurance_effectiveness import (
    build_effectiveness_report,
    build_effectiveness_report_v2,
    compare_effectiveness_v2,
    compare_predeclared_holdout,
)
from scripts.automation.conversation_assurance_effectiveness_contract import (
    RemediationEvidence,
    canonical_digest,
    read_assessment,
    read_policy,
    read_remediation_evidence,
    write_remediation_evidence,
)
from scripts.automation.conversation_assurance_harness import (
    ComparisonRole,
    ImprovementRun,
    read_private_run,
    write_private_run,
)


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
                owning_paths=tuple(sorted(set(owning_paths))),
                task_owned_only=True,
            )
            if evidence_path.exists() or evidence_path.is_symlink():
                if read_remediation_evidence(evidence_path) != remediation_evidence:
                    raise ValueError("remediation_evidence_conflict")
            else:
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
                "effectiveness_policy_digest",
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
    remediation = read_remediation_evidence(remediation_path)
    changed_paths = _git_changed_paths(
        project=project,
        source_revision=baseline.source_revision,
        remediation_revision=remediation.remediation_revision,
    )
    if (
        remediation.changed_path_count != len(changed_paths)
        or remediation.changed_paths_digest != canonical_digest({"paths": list(changed_paths)})
        or any(
            not any(
                path == root.rstrip("/") or path.startswith(f"{root.rstrip('/')}/")
                for root in remediation.owning_paths
            )
            for path in changed_paths
        )
    ):
        raise ValueError("effectiveness_remediation_diff_mismatch")
    base_revision = git_revision(project, policy.authoritative_base_ref)
    result = compare_effectiveness_v2(
        baseline=baseline,
        holdout=holdout,
        baseline_assessment=read_assessment(baseline_assessment_path),
        holdout_assessment=read_assessment(holdout_assessment_path),
        remediation=remediation,
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
    assessment_values = (
        tuple(read_assessment(path) for path in sorted(assessments_root.glob("*.json")))
        if assessments_root.exists()
        else ()
    )
    assessments = {assessment.run_id: assessment for assessment in assessment_values}
    if len(assessments) != len(assessment_values):
        raise ValueError("effectiveness_duplicate_assessment_run_id")
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
    "attribute_remediation",
    "bind_holdout_revision",
    "compare_and_record",
    "compare_and_record_v2",
    "effectiveness_report",
    "effectiveness_report_v2",
    "git_revision",
    "git_revision_contains",
]
