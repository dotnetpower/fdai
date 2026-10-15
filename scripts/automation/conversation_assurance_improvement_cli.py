"""Resumable CLI for one question-to-hardening conversation improvement."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance import (
    PrivateJsonlLedger,
    open_private_lock,
    read_private_text,
)
from fdai.runtime.conversation_assurance_readiness import (
    ReadinessStage,
    RuntimeReadinessInventory,
    assess_capability_readiness,
)
from scripts.automation.conversation_assurance_aks import (
    AksBusinessServiceBinding,
    AksSeriesUnavailableError,
    azure_cli_aks_clusters,
    bind_private_runtime_corpus,
    build_private_aks_corpora,
    build_private_aks_runtime_corpus,
    discover_aks_business_service_bindings,
    local_operating_graph_reader,
)
from scripts.automation.conversation_assurance_cli import (
    _load_private_corpus,
    _start,
)
from scripts.automation.conversation_assurance_effectiveness import (
    attribute_remediation,
    bind_holdout_revision,
    compare_and_record_v2,
    effectiveness_report_v2,
    git_revision,
)
from scripts.automation.conversation_assurance_effectiveness_contract import (
    EffectivenessAssessment,
    EffectivenessPolicy,
    PairCustodyReceipt,
    canonical_digest,
    compose_assessment,
    read_pair_custody_receipt,
    write_assessment,
    write_pair_custody_receipt,
    write_policy,
)
from scripts.automation.conversation_assurance_harness import (
    BrowserRunObservation,
    ComparisonRole,
    FailureClass,
    FindingSeverity,
    GateState,
    ImprovementRun,
    ImprovementState,
    MeasurementOutcome,
    PresentationGate,
    read_private_run,
    validate_question_novelty,
    write_private_run,
)
from scripts.automation.conversation_assurance_reporting import _state_root

_MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
_RUNS_DIRECTORY = "improvement-runs"
_EFFECTIVENESS_LEDGER = "effectiveness-comparisons.jsonl"
_EFFECTIVENESS_ASSESSMENTS_DIRECTORY = "effectiveness-assessments"
_REMEDIATION_EVIDENCE_DIRECTORY = "remediation-evidence"

StartOperation = Callable[[Path, Mapping[str, object]], Awaitable[dict[str, object]]]
_AKS_FUNCTION = "query.resource_state_inventory"
_AKS_CAPABILITY = "aks_business_service_current_state"


def _run_path(project: Path, run_id: str) -> Path:
    return _state_root(project) / _RUNS_DIRECTORY / f"{run_id}.json"


def _run_lock_path(project: Path, run_id: str) -> Path:
    return _state_root(project) / _RUNS_DIRECTORY / f"{run_id}.lock"


def _assessment_path(project: Path, run_id: str) -> Path:
    return _state_root(project) / _EFFECTIVENESS_ASSESSMENTS_DIRECTORY / f"{run_id}.json"


def _remediation_evidence_path(project: Path, run_id: str) -> Path:
    return _state_root(project) / _REMEDIATION_EVIDENCE_DIRECTORY / f"{run_id}.json"


def _git_snapshot(project: Path) -> tuple[str, bool]:
    revision = subprocess.run(  # noqa: S603 - fixed git command
        ("git", "rev-parse", "HEAD"),
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(  # noqa: S603 - fixed git command
            ("git", "status", "--porcelain"),
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return revision, dirty


def _prepare(
    *,
    project: Path,
    corpus_path: Path,
    readiness_path: Path,
    run_id: str,
    capability_id: str,
    required_functions: tuple[str, ...],
    expected_authority: str,
    source_revision: str,
    worktree_dirty: bool,
    comparison_group_id: str | None = None,
    comparison_role: ComparisonRole | None = None,
    cohort_id: str | None = None,
    challenge_family: str | None = None,
    objective_oracle: str | None = None,
    blind_holdout_receipt_digest: str | None = None,
    authoritative_base_ref: str | None = None,
) -> ImprovementRun:
    if worktree_dirty:
        raise ValueError("worktree_not_clean")
    output_path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        if output_path.exists() or output_path.is_symlink():
            raise ValueError("improvement_run_exists")
        corpus = _load_private_corpus(corpus_path)
        if len(corpus.cases) != 1:
            raise ValueError("improvement_requires_one_question")
        case = corpus.cases[0]
        root = _state_root(project)
        campaign_rows = PrivateJsonlLedger(root / "campaigns.jsonl").read(limit=10_000)
        transcript_rows = PrivateJsonlLedger(root / "transcripts.jsonl").read(limit=10_000)
        fingerprint = validate_question_novelty(
            case_id=case.case_id,
            question=case.question,
            campaign_rows=campaign_rows,
            transcript_rows=transcript_rows,
        )
        readiness = _read_private_object(readiness_path)
        readiness_digest = canonical_digest(readiness)
        inventory = RuntimeReadinessInventory.from_dict(readiness)
        selection = assess_capability_readiness(
            capability_id=capability_id,
            enabled=True,
            required_functions=required_functions,
            expected_authority=expected_authority,
            inventory=inventory,
        )
        if not selection.selectable or selection.stage is not ReadinessStage.EVIDENCE_READY:
            _record_preflight_hold(
                project=project,
                capability_id=capability_id,
                cohort_id=cohort_id,
                readiness_digest=readiness_digest,
                reason=selection.unavailable_reason or "readiness_unavailable",
            )
            raise ValueError(f"challenge_unavailable:{selection.unavailable_reason}")
        if selection.provided_authority is None:
            raise ValueError("challenge_authority_unavailable")
        effectiveness_values = (
            cohort_id,
            challenge_family,
            objective_oracle,
            blind_holdout_receipt_digest,
            authoritative_base_ref,
        )
        if comparison_group_id is not None and any(value is None for value in effectiveness_values):
            raise ValueError("effectiveness_comparison_contract_incomplete")
        if comparison_group_id is None and any(value is not None for value in effectiveness_values):
            raise ValueError("effectiveness_contract_requires_comparison_group")
        run = ImprovementRun(
            run_id=run_id,
            case_id=case.case_id,
            question_fingerprint=fingerprint,
            source_revision=source_revision,
            capability_id=capability_id,
            required_functions=required_functions,
            expected_authority=expected_authority,
            provided_authority=selection.provided_authority,
            comparison_group_id=comparison_group_id,
            comparison_role=comparison_role,
            effectiveness_schema_version=("2.0.0" if comparison_group_id is not None else None),
            cohort_id=cohort_id,
            locale=case.locale if comparison_group_id is not None else None,
            suite=case.suite if comparison_group_id is not None else None,
            expected_primary_agent=(
                case.expected_primary_agent if comparison_group_id is not None else None
            ),
            expected_routing_method=(
                case.expected_routing_method if comparison_group_id is not None else None
            ),
            t2_expectation=(str(case.t2_expectation) if comparison_group_id is not None else None),
            challenge_family=challenge_family,
            objective_oracle=objective_oracle,
            blind_holdout_receipt_digest=blind_holdout_receipt_digest,
            authoritative_base_ref=authoritative_base_ref,
            readiness_digest=(readiness_digest if comparison_group_id is not None else None),
        ).validate_dry_run(
            question_count=1,
            child_count=1,
            corpus_digest=corpus.content_digest,
        )
        write_private_run(output_path, run)
        return run


def _pair_receipt_digest(
    *,
    receipt_path: Path,
    corpus_path: Path,
    role: ComparisonRole,
    source_revision: str,
) -> str:
    receipt = read_pair_custody_receipt(receipt_path)
    if receipt.declared_revision != source_revision:
        raise ValueError("pair_custody_revision_mismatch")
    corpus = _load_private_corpus(corpus_path)
    expected_digest = (
        receipt.baseline_corpus_digest
        if role is ComparisonRole.BASELINE
        else receipt.holdout_corpus_digest
    )
    if corpus.content_digest != expected_digest:
        raise ValueError("pair_custody_corpus_mismatch")
    return receipt.content_digest


def _record_preflight_hold(
    *,
    project: Path,
    capability_id: str,
    cohort_id: str | None,
    readiness_digest: str,
    reason: str,
) -> None:
    ledger = PrivateJsonlLedger(_state_root(project) / "preflight-holds.jsonl")
    prior = ledger.read(limit=10_000)
    duplicate = any(
        row.get("capability_id") == capability_id
        and row.get("cohort_id") == cohort_id
        and row.get("readiness_digest") == readiness_digest
        and row.get("reason") == reason
        for row in prior
    )
    if duplicate:
        raise ValueError(f"preflight_no_progress:{reason}")
    ledger.append(
        {
            "schema_version": "1.0.0",
            "capability_id": capability_id,
            "cohort_id": cohort_id,
            "readiness_digest": readiness_digest,
            "reason": reason,
        }
    )


def _prepare_aks_series(
    *,
    project: Path,
    readiness_path: Path,
    runtime_env_path: Path,
    run_prefix: str,
    source_revision: str,
    worktree_dirty: bool,
    bindings: Sequence[AksBusinessServiceBinding] | None = None,
) -> tuple[ImprovementRun, ...]:
    """Prepare three private AKS runs from the current CLI scope and local graph."""

    if worktree_dirty:
        raise ValueError("worktree_not_clean")
    readiness = RuntimeReadinessInventory.from_dict(_read_private_object(readiness_path))
    capability = readiness.capability(_AKS_FUNCTION)
    if (
        capability is None
        or capability.stage is not ReadinessStage.EVIDENCE_READY
        or capability.provided_authority is None
    ):
        raise ValueError("challenge_unavailable:aks_current_state_evidence_unavailable")
    resolved_bindings = (
        tuple(bindings)
        if bindings is not None
        else (
            discover_aks_business_service_bindings(
                azure_clusters=azure_cli_aks_clusters,
                operating_graph=local_operating_graph_reader(runtime_env_path=runtime_env_path),
            )
        )
    )
    output_directory = _state_root(project) / "aks-improvement-corpora" / run_prefix
    expected_corpus_paths = tuple(
        output_directory / f"{run_prefix}-{index}.json" for index in range(1, 4)
    )
    runtime_corpus_path = output_directory / f"{run_prefix}-runtime.json"
    preexisting_paths = {
        path
        for path in (*expected_corpus_paths, runtime_corpus_path)
        if path.exists() or path.is_symlink()
    }
    runs: list[ImprovementRun] = []
    try:
        corpus_paths = build_private_aks_corpora(
            output_directory=output_directory,
            run_prefix=run_prefix,
            bindings=resolved_bindings,
        )
        build_private_aks_runtime_corpus(
            corpus_paths=corpus_paths,
            output_path=runtime_corpus_path,
        )
        for index, corpus_path in enumerate(corpus_paths, start=1):
            runs.append(
                _prepare(
                    project=project,
                    corpus_path=corpus_path,
                    readiness_path=readiness_path,
                    run_id=f"{run_prefix}-{index}",
                    capability_id=_AKS_CAPABILITY,
                    required_functions=(_AKS_FUNCTION,),
                    expected_authority=capability.provided_authority,
                    source_revision=source_revision,
                    worktree_dirty=worktree_dirty,
                )
            )
        runtime_corpus = _load_private_corpus(runtime_corpus_path)
        if len(runtime_corpus.cases) != 3:
            raise ValueError("aks_runtime_corpus_count_invalid")
        binding_lock = open_private_lock(_state_root(project) / "aks-runtime-corpus-binding.lock")
        if binding_lock is None:
            raise ValueError("aks_runtime_corpus_binding_active")
        with binding_lock:
            bind_private_runtime_corpus(
                runtime_env_path=runtime_env_path,
                corpus_path=runtime_corpus_path,
                corpus_digest=runtime_corpus.content_digest,
            )
    except Exception:
        for run in runs:
            _run_path(project, run.run_id).unlink(missing_ok=True)
        for corpus_path in (*expected_corpus_paths, runtime_corpus_path):
            if corpus_path not in preexisting_paths:
                corpus_path.unlink(missing_ok=True)
        raise
    return tuple(runs)


async def _measure(
    *,
    project: Path,
    corpus_path: Path,
    run_id: str,
    source_revision: str,
    worktree_dirty: bool,
    start: StartOperation = _start,
) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        run = read_private_run(path)
        if worktree_dirty or source_revision != run.measurement_source_revision:
            raise ValueError("measurement_revision_drift")
        if not run.retry_allowed:
            raise ValueError("live_question_already_attempted")
        corpus = _load_private_corpus(corpus_path)
        if len(corpus.cases) != 1 or corpus.content_digest != run.corpus_digest:
            raise ValueError("measurement_corpus_drift")
        case = corpus.cases[0]
        fingerprint = validate_question_novelty(
            case_id=case.case_id,
            question=case.question,
            campaign_rows=(),
            transcript_rows=(),
        )
        if case.case_id != run.case_id or fingerprint != run.question_fingerprint:
            raise ValueError("measurement_question_drift")
        transcript_ledger = PrivateJsonlLedger(_state_root(project) / "transcripts.jsonl")
        transcript_count = len(transcript_ledger.read(limit=10_000))
        result: dict[str, object]
        try:
            result = await start(
                project,
                {
                    "suite": "census",
                    "agent": None,
                    "questions": None,
                    "corpus": str(corpus_path.resolve()),
                    "dry_run": False,
                },
            )
        except Exception as error:  # noqa: BLE001 - invocation consumes the single attempt
            result = {"state": "held", "reason": _bounded_reason(error)}
        transcripts = transcript_ledger.read(limit=10_000)
        new_rows = transcripts[transcript_count:]
        transcript = next(
            (row for row in reversed(new_rows) if row.get("case_id") == run.case_id),
            None,
        )
        measured = run.record_measurement(_measurement_outcome(result, transcript))
        write_private_run(path, measured)
        return measured


def _measurement_outcome(
    result: Mapping[str, object],
    transcript: Mapping[str, object] | None,
) -> MeasurementOutcome:
    if transcript is None:
        reason = result.get("reason")
        return MeasurementOutcome(
            terminal_state="held",
            answer_generation_state="unavailable",
            assessment_state="unavailable",
            assessment_reasons=(
                str(reason) if isinstance(reason, str) and reason else "transcript_unavailable",
            ),
        )
    generation = transcript.get("answer_generation")
    answer_generated = transcript.get("answer_digest") is not None
    generation_state = "completed" if answer_generated else "unavailable"
    if isinstance(generation, Mapping) and generation.get("state") in {
        "completed",
        "held",
        "unavailable",
    }:
        generation_state = str(generation["state"])
    assessment_state = str(transcript.get("assessment_state") or "unavailable")
    reasons = transcript.get("assessment_reasons")
    if reasons is not None and (
        not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons)
    ):
        raise ValueError("transcript_assessment_reasons_invalid")
    assessment_reasons = tuple(reasons) if isinstance(reasons, list) else ()
    score = transcript.get("score")
    verdict = transcript.get("verdict")
    return MeasurementOutcome(
        terminal_state=str(transcript.get("terminal_state") or "held"),
        answer_generation_state=generation_state,
        assessment_state=assessment_state,
        assessment_reasons=assessment_reasons,
        score=score if isinstance(score, int) and not isinstance(score, bool) else None,
        verdict=verdict if isinstance(verdict, str) else None,
    )


def _observe_browser(*, project: Path, run_id: str, evidence_path: Path) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        run = read_private_run(path)
        observation = _browser_observation(_read_private_object(evidence_path))
        observed = run.record_browser_observation(observation)
        write_private_run(path, observed)
        return observed


def _record_browser_measurement(
    *,
    project: Path,
    run_id: str,
    evidence_path: Path,
    source_revision: str,
    worktree_dirty: bool,
) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        run = read_private_run(path)
        if worktree_dirty or source_revision != run.measurement_source_revision:
            raise ValueError("measurement_revision_drift")
        if not run.measurement_reserved:
            raise ValueError("browser_measurement_not_armed")
        evidence = _read_private_object(evidence_path)
        request_count = evidence.get("request_count")
        if (
            not isinstance(request_count, int)
            or isinstance(request_count, bool)
            or request_count != 1
            or evidence.get("endpoint_contract") != "/chat/stream"
        ):
            raise ValueError("browser_measurement_request_invalid")
        observation = _browser_observation(evidence)
        if observation.run_id != run.run_id or observation.case_id != run.case_id:
            raise ValueError("browser observation identity does not match the run")
        if observation.question_fingerprint != run.question_fingerprint:
            raise ValueError("browser observation fingerprint does not match the run")
        terminal = evidence.get("terminal")
        if not isinstance(terminal, Mapping):
            raise ValueError("browser_measurement_terminal_invalid")
        measured = run.record_measurement(
            _terminal_measurement_outcome(terminal)
        ).record_browser_observation(observation)
        write_private_run(path, measured)
        return measured


def _record_browser_failure(*, project: Path, run_id: str, reason: str) -> ImprovementRun:
    """Consume an armed attempt when browser custody ends without valid evidence."""

    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        run = read_private_run(path)
        if not run.measurement_reserved:
            raise ValueError("browser_measurement_not_armed")
        failed = run.record_measurement(
            MeasurementOutcome(
                terminal_state="held",
                answer_generation_state="unavailable",
                assessment_state="unavailable",
                assessment_reasons=(reason,),
            )
        ).record_presentation(
            run_record=PresentationGate(GateState.HELD, (reason,)),
            prompt_assembly=PresentationGate(GateState.HELD, (reason,)),
            preparing_answer=PresentationGate(GateState.HELD, (reason,)),
        )
        write_private_run(path, failed)
        return failed


def _run_aks_browser_series(
    *,
    project: Path,
    run_prefix: str,
    origin: str,
    readiness_path: Path,
    source_revision: str,
    worktree_dirty: bool,
) -> tuple[ImprovementRun, ...]:
    """Run prepared AKS cases once each, stopping on the first non-pass."""

    if worktree_dirty:
        raise ValueError("worktree_not_clean")
    worker = project / "console/scripts/conversation-assurance-browser.mjs"
    corpus_root = _state_root(project) / "aks-improvement-corpora" / run_prefix
    runtime_corpus = _load_private_corpus(corpus_root / f"{run_prefix}-runtime.json")
    readiness = RuntimeReadinessInventory.from_dict(_read_private_object(readiness_path))
    if readiness.assurance_corpus_digest != runtime_corpus.content_digest:
        raise ValueError("core_runtime_corpus_not_loaded")
    evidence_root = _state_root(project) / "browser-evidence" / run_prefix
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_root.chmod(0o700)
    completed: list[ImprovementRun] = []
    for index in range(1, 4):
        run_id = f"{run_prefix}-{index}"
        current = read_private_run(_run_path(project, run_id))
        if current.measurement_source_revision != source_revision:
            raise ValueError("measurement_revision_drift")
        _arm_browser(project=project, run_id=run_id, readiness_path=readiness_path)
        evidence_path = evidence_root / f"{index}.json"
        try:
            subprocess.run(  # noqa: S603 - fixed local Node worker and private paths
                (
                    "node",
                    str(worker),
                    "--corpus",
                    str(corpus_root / f"{run_prefix}-{index}.json"),
                    "--run-state",
                    str(_run_path(project, run_id)),
                    "--output",
                    str(evidence_path),
                    "--origin",
                    origin,
                ),
                cwd=project,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
            measured = _record_browser_measurement(
                project=project,
                run_id=run_id,
                evidence_path=evidence_path,
                source_revision=source_revision,
                worktree_dirty=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            measured = _record_browser_failure(
                project=project,
                run_id=run_id,
                reason="browser_worker_failed",
            )
        failure_class = _automatic_failure_class(measured)
        classified = _classify(
            project=project,
            run_id=run_id,
            failure_class=failure_class,
        )
        completed.append(classified)
        if classified.state is not ImprovementState.COMPLETED:
            break
    return tuple(completed)


def _automatic_failure_class(run: ImprovementRun) -> FailureClass | None:
    gates = (run.run_record_gate, run.prompt_assembly_gate, run.preparing_answer_gate)
    if (
        run.assessment_state == "completed"
        and run.verdict == "pass"
        and all(gate.state is GateState.PASSED for gate in gates)
    ):
        return None
    if any(reason.startswith(("authorization_", "auth_")) for reason in run.assessment_reasons):
        return FailureClass.AUTHORIZATION_OR_CONFIGURATION
    if run.assessment_state != "completed":
        return (
            FailureClass.BASELINE_FAILURE
            if "browser_worker_failed" in run.assessment_reasons
            else FailureClass.PROVIDER_OR_EVIDENCE_UNAVAILABLE
        )
    if any(gate.state is not GateState.PASSED for gate in gates):
        return FailureClass.EVALUATION_CONTRACT_DEFECT
    return FailureClass.CODE_DEFECT


def _arm_browser(*, project: Path, run_id: str, readiness_path: Path) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        current = read_private_run(path)
        inventory = RuntimeReadinessInventory.from_dict(_read_private_object(readiness_path))
        selection = assess_capability_readiness(
            capability_id=current.capability_id,
            enabled=True,
            required_functions=current.required_functions,
            expected_authority=current.expected_authority,
            inventory=inventory,
        )
        if not selection.selectable or selection.stage is not ReadinessStage.EVIDENCE_READY:
            raise ValueError(f"preflight_unavailable:{selection.unavailable_reason}")
        if selection.provided_authority != current.provided_authority:
            raise ValueError("preflight_authority_changed")
        if current.measurement_reserved:
            return current
        armed = current.reserve_browser_measurement()
        write_private_run(path, armed)
        return armed


def _record_effectiveness_assessment(
    *,
    project: Path,
    run_id: str,
    evidence_path: Path,
) -> EffectivenessAssessment:
    run = read_private_run(_run_path(project, run_id))
    if run.effectiveness_schema_version != "2.0.0" or run.measurement_attempts != 1:
        raise ValueError("effectiveness_assessment_requires_measured_v2_run")
    assessment = EffectivenessAssessment.from_mapping(_read_private_object(evidence_path))
    if (
        assessment.run_id != run.run_id
        or assessment.case_id != run.case_id
        or assessment.locale != run.locale
    ):
        raise ValueError("effectiveness_assessment_run_mismatch")
    write_assessment(_assessment_path(project, run_id), assessment)
    return assessment


def _terminal_measurement_outcome(value: Mapping[str, object]) -> MeasurementOutcome:
    states: dict[str, str] = {}
    for name in ("terminal_state", "answer_generation_state", "assessment_state"):
        item = value.get(name)
        if not isinstance(item, str) or not item:
            raise ValueError(f"browser_measurement_{name}_invalid")
        states[name] = item
    reasons = value.get("assessment_reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise ValueError("browser_measurement_terminal_invalid")
    score = value.get("score")
    verdict = value.get("verdict")
    return MeasurementOutcome(
        terminal_state=states["terminal_state"],
        answer_generation_state=states["answer_generation_state"],
        assessment_state=states["assessment_state"],
        assessment_reasons=tuple(reasons),
        score=score if isinstance(score, int) and not isinstance(score, bool) else None,
        verdict=verdict if isinstance(verdict, str) else None,
    )


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


def _read_private_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(read_private_text(path, max_bytes=_MAX_EVIDENCE_BYTES))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("private_evidence_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("private_evidence_invalid")
    return {str(key): item for key, item in value.items()}


def _browser_observation(value: Mapping[str, Any]) -> BrowserRunObservation:
    phases = value.get("phase_states")
    if not isinstance(phases, Mapping):
        raise ValueError("browser_observation_invalid")
    return BrowserRunObservation(
        run_id=str(value.get("run_id", "")),
        case_id=str(value.get("case_id", "")),
        question_fingerprint=str(value.get("question_fingerprint", "")),
        session_id=str(value.get("session_id", "")),
        purpose=str(value.get("purpose", "")),
        request_sequence=_integer(value.get("request_sequence")),
        request_sha256=str(value.get("request_sha256", "")),
        trace_receipt_digest=str(value.get("trace_receipt_digest", "")),
        run_record_present=value.get("run_record_present") is True,
        phase_states=tuple((str(key), str(item)) for key, item in phases.items()),
        model_trace_enabled=value.get("model_trace_enabled") is True,
        omitted_model_calls=_integer(value.get("omitted_model_calls")),
        expected_call_kinds=_strings(value.get("expected_call_kinds")),
        observed_call_kinds=_strings(value.get("observed_call_kinds")),
        prompt_manifests_match=value.get("prompt_manifests_match") is True,
        prompt_profiles_visible=value.get("prompt_profiles_visible") is True,
        system_layer_order_valid=value.get("system_layer_order_valid") is True,
        untrusted_data_separated=value.get("untrusted_data_separated") is True,
        preparing_answer_seen=value.get("preparing_answer_seen") is True,
        early_answer_exposed=value.get("early_answer_exposed") is True,
        preparing_answer_overlapped_terminal=(
            value.get("preparing_answer_overlapped_terminal") is True
        ),
        terminal_transition_completed=value.get("terminal_transition_completed") is True,
        sensitive_output_detected=value.get("sensitive_output_detected") is True,
    )


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("browser_observation_invalid")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("browser_observation_invalid")
    return tuple(value)


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
    prepare.add_argument("--blind-holdout-receipt", type=Path)
    prepare.add_argument("--authoritative-base-ref")
    policy = commands.add_parser("init-effectiveness-policy")
    policy.add_argument("--output", type=Path, required=True)
    policy.add_argument("--policy-id", required=True)
    policy.add_argument("--cohort-id", required=True)
    policy.add_argument("--authoritative-base-ref", required=True)
    policy.add_argument("--minimum-pairs", type=int, default=20)
    policy.add_argument("--minimum-pairs-per-locale", type=int, default=10)
    policy.add_argument("--minimum-improvement-rate", type=float, default=0.8)
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
            if arguments.blind_holdout_receipt is not None and comparison_role is None:
                raise ValueError("pair_custody_requires_comparison_role")
            receipt_digest = (
                _pair_receipt_digest(
                    receipt_path=arguments.blind_holdout_receipt.resolve(),
                    corpus_path=arguments.corpus.resolve(),
                    role=comparison_role,
                    source_revision=revision,
                )
                if arguments.blind_holdout_receipt is not None and comparison_role is not None
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
                cohort_id=arguments.cohort_id,
                challenge_family=arguments.challenge_family,
                objective_oracle=arguments.objective_oracle,
                blind_holdout_receipt_digest=receipt_digest,
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
                confidence_level=0.95,
                maximum_regressions=arguments.maximum_regressions,
                maximum_environment_hold_rate=(arguments.maximum_environment_hold_rate),
                maximum_latency_ms_per_measured_run=(arguments.maximum_latency_ms_per_measured_run),
                maximum_model_calls_per_measured_run=(
                    arguments.maximum_model_calls_per_measured_run
                ),
                maximum_cost_usd_per_measured_run=(arguments.maximum_cost_usd_per_measured_run),
            )
            write_policy(arguments.output.resolve(), policy)
            payload = {
                "state": "created",
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
            receipt = PairCustodyReceipt(
                schema_version="1.0.0",
                receipt_id=arguments.receipt_id,
                declared_revision=revision,
                baseline_corpus_digest=baseline.content_digest,
                holdout_corpus_digest=holdout.content_digest,
                custodian_identity_digest=arguments.custodian_identity_digest,
                content_disclosed_to_repair_agent=False,
            )
            write_pair_custody_receipt(arguments.output.resolve(), receipt)
            payload = {
                "state": "sealed",
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
                        _read_private_object(arguments.validation_receipt.resolve())
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
                evidence_path=arguments.evidence.resolve(),
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
                locale=run.locale,
                answer_gate=_read_private_object(arguments.answer_gate.resolve()),
                browser_evidence=_read_private_object(arguments.browser_evidence.resolve()),
            )
            write_assessment(_assessment_path(project, run.run_id), assessment)
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
                policy_path=(project / arguments.policy).resolve(),
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
                policy_path=(project / arguments.policy).resolve(),
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
