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
from scripts.automation.conversation_assurance_cli import (
    _load_private_corpus,
    _start,
    _state_root,
)
from scripts.automation.conversation_assurance_harness import (
    BrowserRunObservation,
    FailureClass,
    FindingSeverity,
    ImprovementRun,
    MeasurementOutcome,
    read_private_run,
    validate_question_novelty,
    write_private_run,
)

_MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
_RUNS_DIRECTORY = "improvement-runs"

StartOperation = Callable[[Path, Mapping[str, object]], Awaitable[dict[str, object]]]


def _run_path(project: Path, run_id: str) -> Path:
    return _state_root(project) / _RUNS_DIRECTORY / f"{run_id}.json"


def _run_lock_path(project: Path, run_id: str) -> Path:
    return _state_root(project) / _RUNS_DIRECTORY / f"{run_id}.lock"


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
        inventory = RuntimeReadinessInventory.from_dict(readiness)
        selection = assess_capability_readiness(
            capability_id=capability_id,
            enabled=True,
            required_functions=required_functions,
            expected_authority=expected_authority,
            inventory=inventory,
        )
        if not selection.selectable or selection.stage is not ReadinessStage.EVIDENCE_READY:
            raise ValueError(f"challenge_unavailable:{selection.unavailable_reason}")
        if selection.provided_authority is None:
            raise ValueError("challenge_authority_unavailable")
        run = ImprovementRun(
            run_id=run_id,
            case_id=case.case_id,
            question_fingerprint=fingerprint,
            source_revision=source_revision,
            capability_id=capability_id,
            required_functions=required_functions,
            expected_authority=expected_authority,
            provided_authority=selection.provided_authority,
        ).validate_dry_run(
            question_count=1,
            child_count=1,
            corpus_digest=corpus.content_digest,
        )
        write_private_run(output_path, run)
        return run


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
        if worktree_dirty or source_revision != run.source_revision:
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
        if worktree_dirty or source_revision != run.source_revision:
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


def _arm_browser(*, project: Path, run_id: str) -> ImprovementRun:
    path = _run_path(project, run_id)
    lock = open_private_lock(_run_lock_path(project, run_id))
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        current = read_private_run(path)
        if current.measurement_reserved:
            return current
        armed = current.reserve_browser_measurement()
        write_private_run(path, armed)
        return armed


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
    measure = commands.add_parser("measure-headless")
    measure.add_argument("--corpus", type=Path, required=True)
    measure.add_argument("--run-id", required=True)
    arm_browser = commands.add_parser("arm-browser")
    arm_browser.add_argument("--run-id", required=True)
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project = arguments.project.resolve()
    try:
        if arguments.operation == "prepare":
            revision, dirty = _git_snapshot(project)
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
            )
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
        elif arguments.operation == "record-browser-measurement":
            revision, dirty = _git_snapshot(project)
            run = _record_browser_measurement(
                project=project,
                run_id=arguments.run_id,
                evidence_path=arguments.evidence.resolve(),
                source_revision=revision,
                worktree_dirty=dirty,
            )
        elif arguments.operation == "arm-browser":
            run = _arm_browser(project=project, run_id=arguments.run_id)
        elif arguments.operation == "observe-browser":
            run = _observe_browser(
                project=project,
                run_id=arguments.run_id,
                evidence_path=arguments.evidence.resolve(),
            )
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
        else:
            run = read_private_run(_run_path(project, arguments.run_id))
        payload = _summary(run)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        payload = {"state": "held", "reason": _bounded_reason(error)}
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


__all__ = ["main"]
