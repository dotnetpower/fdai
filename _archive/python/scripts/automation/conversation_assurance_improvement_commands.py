"""Command facade for one-question conversation improvement."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from fdai.core.conversation_assurance import open_private_lock
from scripts.automation.conversation_assurance_aks import AksSeriesUnavailableError
from scripts.automation.conversation_assurance_cli import _load_private_corpus
from scripts.automation.conversation_assurance_effectiveness_contract import (
    EffectivenessPolicy,
    PairCustodyReceipt,
    compose_assessment,
    read_policy,
)
from scripts.automation.conversation_assurance_effectiveness_io import (
    attribute_remediation,
    bind_holdout_revision,
    compare_and_record_v2,
    effectiveness_report_v2,
    git_revision,
)
from scripts.automation.conversation_assurance_harness import (
    ComparisonRole,
    FailureClass,
    FindingSeverity,
    ImprovementRun,
    read_private_run,
    write_private_run,
)
from scripts.automation.conversation_assurance_improvement_cli import (
    _EFFECTIVENESS_ASSESSMENTS_DIRECTORY,
    _EFFECTIVENESS_LEDGER,
    _RUNS_DIRECTORY,
    _arm_browser,
    _assessment_path,
    _git_snapshot,
    _measure,
    _observe_browser,
    _pair_receipt_digest,
    _prepare,
    _prepare_aks_series,
    _private_output_path,
    _read_private_object,
    _record_browser_measurement,
    _record_effectiveness_assessment,
    _remediation_evidence_path,
    _run_aks_browser_series,
    _run_lock_path,
    _run_path,
    _write_assessment_idempotent,
    _write_pair_receipt_idempotent,
    _write_policy_idempotent,
)
from scripts.automation.conversation_assurance_reporting import _state_root


def _classify(*, project: Path, run_id: str, failure_class: FailureClass | None) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        classified = read_private_run(path).classify(failure_class)
        write_private_run(path, classified)
        return classified


def _hardening_round(
    *,
    project: Path,
    run_id: str,
    severity: FindingSeverity,
    reviewer_scope: str,
    finding_count: int,
    fixed_count: int,
    validation_passed: bool,
) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        hardened = read_private_run(path).record_hardening_round(
            severity,
            reviewer_scope=reviewer_scope,
            finding_count=finding_count,
            fixed_count=fixed_count,
            validation_passed=validation_passed,
        )
        write_private_run(path, hardened)
        return hardened


def _bounded_reason(error: Exception) -> str:
    value = str(error)
    return value if value and len(value) <= 128 else f"measurement_error:{type(error).__name__}"


def _summary(run: ImprovementRun) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "case_id": run.case_id,
        "state": run.state,
        "source_revision": run.source_revision,
        "measurement_revision": run.measurement_source_revision,
        "measurement_attempts": run.measurement_attempts,
        "retry_allowed": run.retry_allowed,
        "terminal_state": run.terminal_state,
        "answer_generation_state": run.answer_generation_state,
        "assessment_state": run.assessment_state,
        "assessment_reasons": list(run.assessment_reasons),
        "score": run.score,
        "verdict": run.verdict,
        "qualification": run.qualification,
        "failure_class": run.failure_class,
        "comparison_group_id": run.comparison_group_id,
        "comparison_role": run.comparison_role,
        "effectiveness_schema_version": run.effectiveness_schema_version,
        "effectiveness_policy_digest": run.effectiveness_policy_digest,
        "cohort_id": run.cohort_id,
        "locale": run.locale,
        "challenge_family": run.challenge_family,
        "objective_oracle": run.objective_oracle,
        "authoritative_base_ref": run.authoritative_base_ref,
        "readiness_digest": run.readiness_digest,
        "remediation_revision": run.remediation_revision,
        "run_record_gate": run.run_record_gate.state,
        "prompt_assembly_gate": run.prompt_assembly_gate.state,
        "preparing_answer_gate": run.preparing_answer_gate.state,
        "hardening_rounds": run.hardening_rounds,
        "remaining_max_severity": run.remaining_max_severity,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="operation", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--corpus", type=Path, required=True)
    prepare.add_argument("--readiness", type=Path, required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--capability", required=True)
    prepare.add_argument("--function", action="append", dest="functions", required=True)
    prepare.add_argument("--expected-authority", required=True)
    prepare.add_argument("--comparison-group")
    prepare.add_argument(
        "--comparison-role",
        choices=tuple(item.value for item in ComparisonRole),
    )
    prepare.add_argument("--cohort-id")
    prepare.add_argument("--challenge-family")
    prepare.add_argument("--objective-oracle")
    prepare.add_argument(
        "--pair-custody-receipt",
        "--blind-holdout-receipt",
        dest="pair_custody_receipt",
        type=Path,
    )
    prepare.add_argument("--authoritative-base-ref")
    policy = commands.add_parser("init-effectiveness-policy")
    policy.add_argument("--output", type=Path, required=True)
    policy.add_argument("--policy-id", required=True)
    policy.add_argument("--cohort-id", required=True)
    policy.add_argument("--authoritative-base-ref", required=True)
    policy.add_argument("--minimum-pairs", type=int, default=20)
    policy.add_argument("--minimum-pairs-per-locale", type=int, default=10)
    policy.add_argument("--minimum-improvement-rate", type=float, default=0.8)
    policy.add_argument("--minimum-pair-ratio-delta", type=float, default=0.1)
    policy.add_argument("--maximum-regressions", type=int, default=0)
    policy.add_argument("--maximum-environment-hold-rate", type=float, default=0.1)
    policy.add_argument(
        "--maximum-latency-ms-per-measured-run",
        type=int,
        default=120_000,
    )
    policy.add_argument(
        "--maximum-model-calls-per-measured-run",
        type=float,
        default=10.0,
    )
    policy.add_argument(
        "--maximum-cost-usd-per-measured-run",
        type=float,
        default=1.0,
    )
    custody = commands.add_parser("seal-effectiveness-pair")
    custody.add_argument("--baseline-corpus", type=Path, required=True)
    custody.add_argument("--holdout-corpus", type=Path, required=True)
    custody.add_argument("--output", type=Path, required=True)
    custody.add_argument("--receipt-id", required=True)
    custody.add_argument("--custodian-identity-digest", required=True)
    custody.add_argument("--policy", type=Path, required=True)
    custody.add_argument("--comparison-group", required=True)
    custody.add_argument("--challenge-family", required=True)
    custody.add_argument("--objective-oracle", required=True)
    prepare_aks = commands.add_parser("prepare-aks-series")
    prepare_aks.add_argument("--run-prefix", required=True)
    prepare_aks.add_argument(
        "--readiness",
        type=Path,
        default=Path(".fdai/conversation-assurance/runtime-readiness.json"),
    )
    prepare_aks.add_argument(
        "--runtime-env",
        type=Path,
        default=Path(".fdai/local-runtime.env"),
    )
    run_aks = commands.add_parser("run-aks-series")
    run_aks.add_argument("--run-prefix", required=True)
    run_aks.add_argument("--origin", default="http://localhost:5273")
    run_aks.add_argument(
        "--readiness",
        type=Path,
        default=Path(".fdai/conversation-assurance/runtime-readiness.json"),
    )
    measure = commands.add_parser("measure-headless")
    measure.add_argument("--corpus", type=Path, required=True)
    measure.add_argument("--run-id", required=True)
    arm_browser = commands.add_parser("arm-browser")
    arm_browser.add_argument("--run-id", required=True)
    arm_browser.add_argument(
        "--readiness",
        type=Path,
        default=Path(".fdai/conversation-assurance/runtime-readiness.json"),
    )
    browser_measure = commands.add_parser("record-browser-measurement")
    browser_measure.add_argument("--run-id", required=True)
    browser_measure.add_argument("--evidence", type=Path, required=True)
    observe = commands.add_parser("observe-browser")
    observe.add_argument("--run-id", required=True)
    observe.add_argument("--evidence", type=Path, required=True)
    classify = commands.add_parser("classify")
    classify.add_argument("--run-id", required=True)
    classify.add_argument(
        "--failure-class",
        choices=("none", *(item.value for item in FailureClass)),
        required=True,
    )
    hardening = commands.add_parser("hardening-round")
    hardening.add_argument("--run-id", required=True)
    hardening.add_argument(
        "--severity",
        choices=tuple(item.value for item in FindingSeverity),
        required=True,
    )
    hardening.add_argument("--reviewer-scope", required=True)
    hardening.add_argument("--finding-count", type=int, required=True)
    hardening.add_argument("--fixed-count", type=int, required=True)
    hardening.add_argument("--validation-passed", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--run-id", required=True)
    remediation = commands.add_parser("attribute-remediation")
    remediation.add_argument("--run-id", required=True)
    remediation.add_argument("--revision", default="HEAD")
    remediation.add_argument("--owning-path", action="append", dest="owning_paths")
    remediation.add_argument("--validation-receipt", type=Path)
    assessment = commands.add_parser("record-effectiveness-assessment")
    assessment.add_argument("--run-id", required=True)
    assessment.add_argument("--evidence", type=Path, required=True)
    compose = commands.add_parser("compose-effectiveness-assessment")
    compose.add_argument("--run-id", required=True)
    compose.add_argument("--answer-gate", type=Path, required=True)
    compose.add_argument("--browser-evidence", type=Path, required=True)
    bind_holdout = commands.add_parser("bind-holdout")
    bind_holdout.add_argument("--baseline-run", required=True)
    bind_holdout.add_argument("--holdout-run", required=True)
    bind_holdout.add_argument("--revision", default="HEAD")
    compare = commands.add_parser("compare-effectiveness")
    compare.add_argument("--baseline-run", required=True)
    compare.add_argument("--holdout-run", required=True)
    compare.add_argument(
        "--policy",
        type=Path,
        default=Path(".fdai/conversation-assurance/effectiveness-policy.json"),
    )
    effectiveness = commands.add_parser("effectiveness")
    effectiveness.add_argument(
        "--policy",
        type=Path,
        default=Path(".fdai/conversation-assurance/effectiveness-policy.json"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project = arguments.project.resolve()
    try:
        if arguments.operation == "prepare":
            revision, dirty = _git_snapshot(project)
            comparison_role = (
                ComparisonRole(arguments.comparison_role)
                if arguments.comparison_role is not None
                else None
            )
            if arguments.pair_custody_receipt is not None and comparison_role is None:
                raise ValueError("pair_custody_requires_comparison_role")
            if arguments.pair_custody_receipt is not None and (
                arguments.cohort_id is None
                or arguments.comparison_group is None
                or arguments.challenge_family is None
                or arguments.objective_oracle is None
                or arguments.authoritative_base_ref is None
            ):
                raise ValueError("effectiveness_comparison_contract_incomplete")
            custody_receipt = (
                _pair_receipt_digest(
                    receipt_path=_private_output_path(project, arguments.pair_custody_receipt),
                    corpus_path=arguments.corpus.resolve(),
                    role=comparison_role,
                    source_revision=revision,
                    cohort_id=arguments.cohort_id,
                    comparison_group_id=arguments.comparison_group,
                    challenge_family=arguments.challenge_family,
                    objective_oracle=arguments.objective_oracle,
                    authoritative_base_ref=arguments.authoritative_base_ref,
                )
                if arguments.pair_custody_receipt is not None and comparison_role is not None
                else None
            )
            run = _prepare(
                project=project,
                corpus_path=arguments.corpus.resolve(),
                readiness_path=arguments.readiness.resolve(),
                run_id=arguments.run_id,
                capability_id=arguments.capability,
                required_functions=tuple(arguments.functions),
                expected_authority=arguments.expected_authority,
                source_revision=revision,
                worktree_dirty=dirty,
                comparison_group_id=arguments.comparison_group,
                comparison_role=comparison_role,
                effectiveness_policy_digest=(
                    custody_receipt.policy_digest if custody_receipt is not None else None
                ),
                cohort_id=arguments.cohort_id,
                challenge_family=arguments.challenge_family,
                objective_oracle=arguments.objective_oracle,
                blind_holdout_receipt_digest=(
                    custody_receipt.content_digest if custody_receipt is not None else None
                ),
                authoritative_base_ref=arguments.authoritative_base_ref,
            )
            payload = _summary(run)
        elif arguments.operation == "init-effectiveness-policy":
            policy = EffectivenessPolicy(
                schema_version="1.0.0",
                policy_id=arguments.policy_id,
                cohort_id=arguments.cohort_id,
                authoritative_base_ref=arguments.authoritative_base_ref,
                required_locales=("en", "ko"),
                minimum_pairs=arguments.minimum_pairs,
                minimum_pairs_per_locale=arguments.minimum_pairs_per_locale,
                minimum_improvement_rate=arguments.minimum_improvement_rate,
                minimum_pair_ratio_delta=arguments.minimum_pair_ratio_delta,
                confidence_level=0.95,
                maximum_regressions=arguments.maximum_regressions,
                maximum_environment_hold_rate=(arguments.maximum_environment_hold_rate),
                maximum_latency_ms_per_measured_run=(arguments.maximum_latency_ms_per_measured_run),
                maximum_model_calls_per_measured_run=(
                    arguments.maximum_model_calls_per_measured_run
                ),
                maximum_cost_usd_per_measured_run=(arguments.maximum_cost_usd_per_measured_run),
            )
            policy_path = _private_output_path(project, arguments.output)
            policy_state = _write_policy_idempotent(policy_path, policy)
            payload = {
                "state": policy_state,
                "policy_id": policy.policy_id,
                "policy_digest": policy.content_digest,
                "qualification_authority": False,
                "execution_authority": False,
            }
        elif arguments.operation == "seal-effectiveness-pair":
            revision, dirty = _git_snapshot(project)
            if dirty:
                raise ValueError("worktree_not_clean")
            baseline = _load_private_corpus(arguments.baseline_corpus.resolve())
            holdout = _load_private_corpus(arguments.holdout_corpus.resolve())
            if len(baseline.cases) != 1 or len(holdout.cases) != 1:
                raise ValueError("effectiveness_pair_requires_one_question_each")
            baseline_case = baseline.cases[0]
            holdout_case = holdout.cases[0]
            case_contract = (
                "locale",
                "suite",
                "expected_primary_agent",
                "expected_routing_method",
                "t2_expectation",
            )
            if any(
                getattr(baseline_case, name) != getattr(holdout_case, name)
                for name in case_contract
            ):
                raise ValueError("effectiveness_pair_case_contract_mismatch")
            policy = read_policy(_private_output_path(project, arguments.policy))
            receipt = PairCustodyReceipt(
                schema_version="1.0.0",
                receipt_id=arguments.receipt_id,
                policy_digest=policy.content_digest,
                cohort_id=policy.cohort_id,
                comparison_group_id=arguments.comparison_group,
                authoritative_base_ref=policy.authoritative_base_ref,
                declared_revision=revision,
                baseline_corpus_digest=baseline.content_digest,
                holdout_corpus_digest=holdout.content_digest,
                custodian_identity_digest=arguments.custodian_identity_digest,
                locale=baseline_case.locale,
                suite=baseline_case.suite,
                expected_primary_agent=baseline_case.expected_primary_agent,
                expected_routing_method=baseline_case.expected_routing_method,
                t2_expectation=str(baseline_case.t2_expectation),
                challenge_family=arguments.challenge_family,
                objective_oracle=arguments.objective_oracle,
                content_disclosed_to_repair_agent=False,
            )
            receipt_path = _private_output_path(project, arguments.output)
            receipt_state = _write_pair_receipt_idempotent(receipt_path, receipt)
            payload = {
                "state": receipt_state,
                "receipt_id": receipt.receipt_id,
                "receipt_digest": receipt.content_digest,
                "qualification_authority": False,
                "execution_authority": False,
            }
        elif arguments.operation == "prepare-aks-series":
            revision, dirty = _git_snapshot(project)
            runs = _prepare_aks_series(
                project=project,
                readiness_path=(project / arguments.readiness).resolve(),
                runtime_env_path=(project / arguments.runtime_env).resolve(),
                run_prefix=arguments.run_prefix,
                source_revision=revision,
                worktree_dirty=dirty,
            )
            payload = {
                "state": "prepared",
                "question_count": len(runs),
                "core_restart_required": True,
                "runs": [_summary(run) for run in runs],
            }
        elif arguments.operation == "run-aks-series":
            revision, dirty = _git_snapshot(project)
            runs = _run_aks_browser_series(
                project=project,
                run_prefix=arguments.run_prefix,
                origin=arguments.origin,
                readiness_path=(project / arguments.readiness).resolve(),
                source_revision=revision,
                worktree_dirty=dirty,
            )
            payload = {
                "state": runs[-1].state if runs else "held",
                "evaluated": len(runs),
                "requested": 3,
                "runs": [_summary(run) for run in runs],
            }
        elif arguments.operation == "measure-headless":
            revision, dirty = _git_snapshot(project)
            run = asyncio.run(
                _measure(
                    project=project,
                    corpus_path=arguments.corpus.resolve(),
                    run_id=arguments.run_id,
                    source_revision=revision,
                    worktree_dirty=dirty,
                )
            )
            payload = _summary(run)
        elif arguments.operation == "record-browser-measurement":
            revision, dirty = _git_snapshot(project)
            run = _record_browser_measurement(
                project=project,
                run_id=arguments.run_id,
                evidence_path=arguments.evidence.resolve(),
                source_revision=revision,
                worktree_dirty=dirty,
            )
            payload = _summary(run)
        elif arguments.operation == "arm-browser":
            run = _arm_browser(
                project=project,
                run_id=arguments.run_id,
                readiness_path=(project / arguments.readiness).resolve(),
            )
            payload = _summary(run)
        elif arguments.operation == "observe-browser":
            run = _observe_browser(
                project=project,
                run_id=arguments.run_id,
                evidence_path=arguments.evidence.resolve(),
            )
            payload = _summary(run)
        elif arguments.operation == "classify":
            run = _classify(
                project=project,
                run_id=arguments.run_id,
                failure_class=(
                    None
                    if arguments.failure_class == "none"
                    else FailureClass(arguments.failure_class)
                ),
            )
            payload = _summary(run)
        elif arguments.operation == "hardening-round":
            run = _hardening_round(
                project=project,
                run_id=arguments.run_id,
                severity=FindingSeverity(arguments.severity),
                reviewer_scope=arguments.reviewer_scope,
                finding_count=arguments.finding_count,
                fixed_count=arguments.fixed_count,
                validation_passed=arguments.validation_passed,
            )
            payload = _summary(run)
        elif arguments.operation == "attribute-remediation":
            revision, dirty = _git_snapshot(project)
            requested_revision = git_revision(project, arguments.revision)
            if arguments.revision == "HEAD" and requested_revision != revision:
                raise ValueError("remediation_revision_drift")
            payload = _summary(
                attribute_remediation(
                    project=project,
                    run_path=_run_path(project, arguments.run_id),
                    lock_path=_run_lock_path(project, arguments.run_id),
                    revision=requested_revision,
                    worktree_dirty=dirty,
                    owning_paths=tuple(arguments.owning_paths or ()),
                    validation_receipt=(
                        _read_private_object(
                            _private_output_path(project, arguments.validation_receipt)
                        )
                        if arguments.validation_receipt is not None
                        else None
                    ),
                    evidence_path=_remediation_evidence_path(project, arguments.run_id),
                )
            )
        elif arguments.operation == "record-effectiveness-assessment":
            assessment = _record_effectiveness_assessment(
                project=project,
                run_id=arguments.run_id,
                evidence_path=_private_output_path(project, arguments.evidence),
            )
            payload = {
                "state": "recorded",
                "run_id": assessment.run_id,
                "assessment_digest": assessment.content_digest,
                "assurance_passed": assessment.assurance_passed,
                "qualification_authority": False,
                "execution_authority": False,
            }
        elif arguments.operation == "compose-effectiveness-assessment":
            run = read_private_run(_run_path(project, arguments.run_id))
            if (
                run.effectiveness_schema_version != "2.0.0"
                or run.measurement_attempts != 1
                or run.locale is None
            ):
                raise ValueError("effectiveness_assessment_requires_measured_v2_run")
            assessment = compose_assessment(
                run_id=run.run_id,
                case_id=run.case_id,
                question_fingerprint=run.question_fingerprint,
                measurement_revision=run.measurement_source_revision,
                locale=run.locale,
                answer_gate=_read_private_object(
                    _private_output_path(project, arguments.answer_gate)
                ),
                browser_evidence=_read_private_object(
                    _private_output_path(project, arguments.browser_evidence)
                ),
            )
            _write_assessment_idempotent(_assessment_path(project, run.run_id), assessment)
            payload = {
                "state": "recorded",
                "run_id": assessment.run_id,
                "assessment_digest": assessment.content_digest,
                "assurance_passed": assessment.assurance_passed,
                "qualification_authority": False,
                "execution_authority": False,
            }
        elif arguments.operation == "compare-effectiveness":
            payload = compare_and_record_v2(
                project=project,
                baseline_path=_run_path(project, arguments.baseline_run),
                holdout_path=_run_path(project, arguments.holdout_run),
                baseline_assessment_path=_assessment_path(project, arguments.baseline_run),
                holdout_assessment_path=_assessment_path(project, arguments.holdout_run),
                remediation_path=_remediation_evidence_path(project, arguments.baseline_run),
                policy_path=_private_output_path(project, project / arguments.policy),
                ledger_path=_state_root(project) / _EFFECTIVENESS_LEDGER,
            )
        elif arguments.operation == "bind-holdout":
            revision, dirty = _git_snapshot(project)
            requested_revision = git_revision(project, arguments.revision)
            if arguments.revision == "HEAD" and requested_revision != revision:
                raise ValueError("holdout_revision_drift")
            payload = _summary(
                bind_holdout_revision(
                    project=project,
                    baseline_path=_run_path(project, arguments.baseline_run),
                    holdout_path=_run_path(project, arguments.holdout_run),
                    holdout_lock_path=_run_lock_path(project, arguments.holdout_run),
                    revision=requested_revision,
                    worktree_dirty=dirty,
                )
            )
        elif arguments.operation == "effectiveness":
            payload = effectiveness_report_v2(
                project=project,
                runs_root=_state_root(project) / _RUNS_DIRECTORY,
                assessments_root=(_state_root(project) / _EFFECTIVENESS_ASSESSMENTS_DIRECTORY),
                ledger_path=_state_root(project) / _EFFECTIVENESS_LEDGER,
                policy_path=_private_output_path(project, project / arguments.policy),
                preflight_holds_path=_state_root(project) / "preflight-holds.jsonl",
            )
        else:
            run = read_private_run(_run_path(project, arguments.run_id))
            payload = _summary(run)
    except (
        AksSeriesUnavailableError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        payload = {"state": "held", "reason": _bounded_reason(error)}
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


__all__ = ["main"]
