"""Resumable CLI for one question-to-hardening conversation improvement."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance import (
    PrivateJsonlLedger,
    open_private_lock,
    private_marker_exists,
    read_private_text,
)
from fdai.runtime.conversation_assurance_readiness import (
    ReadinessStage,
    RuntimeReadinessInventory,
    assess_capability_readiness,
)
from scripts.automation.conversation_assurance_aks import (
    AksBusinessServiceBinding,
    azure_cli_aks_clusters,
    bind_private_runtime_corpus,
    build_private_aks_corpora,
    build_private_aks_runtime_corpus,
    discover_aks_business_service_bindings,
    local_operating_graph_reader,
)
from scripts.automation.conversation_assurance_browser_evidence import (
    browser_observation,
    terminal_measurement_outcome,
)
from scripts.automation.conversation_assurance_cli import (
    _load_private_corpus,
    _start,
)
from scripts.automation.conversation_assurance_effectiveness_contract import (
    EffectivenessAssessment,
    EffectivenessPolicy,
    PairCustodyReceipt,
    canonical_digest,
    read_assessment,
    read_pair_custody_receipt,
    read_policy,
    write_assessment,
    write_pair_custody_receipt,
    write_policy,
)
from scripts.automation.conversation_assurance_harness import (
    ComparisonRole,
    GateState,
    ImprovementRun,
    ImprovementState,
    MeasurementOutcome,
    PresentationGate,
    read_private_run,
    validate_question_novelty,
    write_private_run,
)
from scripts.automation.conversation_assurance_improvement_state import (
    automatic_failure_class as _automatic_failure_class,
)
from scripts.automation.conversation_assurance_improvement_state import (
    bounded_reason as _bounded_reason,
)
from scripts.automation.conversation_assurance_improvement_state import (
    classify_run,
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


def _private_output_path(project: Path, path: Path) -> Path:
    resolved = path.resolve()
    state_root = _state_root(project).resolve()
    if not resolved.is_relative_to(state_root):
        raise ValueError("effectiveness_output_must_be_private_state")
    return resolved


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
    effectiveness_policy_digest: str | None = None,
    cohort_id: str | None = None,
    challenge_family: str | None = None,
    objective_oracle: str | None = None,
    blind_holdout_receipt_digest: str | None = None,
    authoritative_base_ref: str | None = None,
) -> ImprovementRun:
    if worktree_dirty:
        raise ValueError("worktree_not_clean")
    if private_marker_exists(_state_root(project) / "STOP"):
        raise ValueError("stop_requested")
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
            effectiveness_policy_digest,
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
            effectiveness_policy_digest=effectiveness_policy_digest,
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
    cohort_id: str,
    comparison_group_id: str,
    challenge_family: str,
    objective_oracle: str,
    authoritative_base_ref: str,
) -> PairCustodyReceipt:
    receipt = read_pair_custody_receipt(receipt_path)
    if receipt.declared_revision != source_revision:
        raise ValueError("pair_custody_revision_mismatch")
    corpus = _load_private_corpus(corpus_path)
    if len(corpus.cases) != 1:
        raise ValueError("effectiveness_pair_requires_one_question_each")
    case = corpus.cases[0]
    if (
        receipt.cohort_id != cohort_id
        or receipt.comparison_group_id != comparison_group_id
        or receipt.challenge_family != challenge_family
        or receipt.objective_oracle != objective_oracle
        or receipt.authoritative_base_ref != authoritative_base_ref
        or receipt.locale != case.locale
        or receipt.suite != case.suite
        or receipt.expected_primary_agent != case.expected_primary_agent
        or receipt.expected_routing_method != case.expected_routing_method
        or receipt.t2_expectation != str(case.t2_expectation)
    ):
        raise ValueError("pair_custody_contract_mismatch")
    expected_digest = (
        receipt.baseline_corpus_digest
        if role is ComparisonRole.BASELINE
        else receipt.holdout_corpus_digest
    )
    if corpus.content_digest != expected_digest:
        raise ValueError("pair_custody_corpus_mismatch")
    return receipt


def _write_policy_idempotent(path: Path, policy: EffectivenessPolicy) -> str:
    lock = open_private_lock(path.with_suffix(".lock"))
    if lock is None:
        raise ValueError("effectiveness_policy_active")
    with lock:
        if path.exists() or path.is_symlink():
            if read_policy(path) != policy:
                raise ValueError("effectiveness_policy_conflict")
            return "existing"
        write_policy(path, policy)
        return "created"


def _write_pair_receipt_idempotent(
    path: Path,
    receipt: PairCustodyReceipt,
) -> str:
    lock = open_private_lock(path.with_suffix(".lock"))
    if lock is None:
        raise ValueError("pair_custody_receipt_active")
    with lock:
        if path.exists() or path.is_symlink():
            if read_pair_custody_receipt(path) != receipt:
                raise ValueError("pair_custody_receipt_conflict")
            return "existing"
        write_pair_custody_receipt(path, receipt)
        return "sealed"


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
    except Exception:  # noqa: BLE001 - rollback every partially prepared private artifact
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
        observation = browser_observation(_read_private_object(evidence_path))
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
        observation = browser_observation(evidence)
        if observation.run_id != run.run_id or observation.case_id != run.case_id:
            raise ValueError("browser observation identity does not match the run")
        if observation.question_fingerprint != run.question_fingerprint:
            raise ValueError("browser observation fingerprint does not match the run")
        terminal = evidence.get("terminal")
        if not isinstance(terminal, Mapping):
            raise ValueError("browser_measurement_terminal_invalid")
        measured = run.record_measurement(
            terminal_measurement_outcome(terminal)
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
        classified = classify_run(
            run_path=_run_path(project, run_id),
            lock_path=_run_lock_path(project, run_id),
            failure_class=failure_class,
        )
        completed.append(classified)
        if classified.state is not ImprovementState.COMPLETED:
            break
    return tuple(completed)


def _read_private_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(read_private_text(path, max_bytes=_MAX_EVIDENCE_BYTES))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("private_evidence_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("private_evidence_invalid")
    return {str(key): item for key, item in value.items()}


def _arm_browser(*, project: Path, run_id: str, readiness_path: Path) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        current = read_private_run(path)
        if private_marker_exists(_state_root(project) / "STOP"):
            raise ValueError("stop_requested")
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
        or assessment.question_fingerprint != run.question_fingerprint
        or assessment.measurement_revision != run.measurement_source_revision
        or assessment.locale != run.locale
    ):
        raise ValueError("effectiveness_assessment_run_mismatch")
    _write_assessment_idempotent(_assessment_path(project, run_id), assessment)
    return assessment


def _write_assessment_idempotent(
    path: Path,
    assessment: EffectivenessAssessment,
) -> None:
    lock = open_private_lock(path.with_suffix(".lock"))
    if lock is None:
        raise ValueError("effectiveness_assessment_active")
    with lock:
        if path.exists() or path.is_symlink():
            if read_assessment(path) != assessment:
                raise ValueError("effectiveness_assessment_conflict")
            return
        write_assessment(path, assessment)
