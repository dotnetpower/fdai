from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from scripts.automation.conversation_assurance_harness import (
    BrowserRunObservation,
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


def _prepared() -> ImprovementRun:
    return ImprovementRun(
        run_id="improvement-one",
        case_id="new-case-one",
        question_fingerprint="sha256:" + "a" * 64,
        source_revision="b" * 40,
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure-resource-graph",
        provided_authority="azure-resource-graph",
    )


def _validated() -> ImprovementRun:
    return _prepared().validate_dry_run(
        question_count=1,
        child_count=1,
        corpus_digest="c" * 64,
    )


def test_incomplete_assessment_preserves_answer_state_without_score() -> None:
    run = _validated().record_measurement(
        MeasurementOutcome(
            terminal_state="held",
            answer_generation_state="completed",
            assessment_state="deferred",
            assessment_reasons=("provider_http_429",),
        )
    )

    assert run.state is ImprovementState.HELD
    assert run.answer_generation_state == "completed"
    assert run.assessment_state == "deferred"
    assert run.score is None
    assert run.verdict is None
    assert run.retry_allowed is False

    with pytest.raises(ValueError, match="validated or browser-armed"):
        run.record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=30,
                verdict="pass",
            )
        )


def test_pass_requires_all_web_presentation_gates() -> None:
    measured = _validated().record_measurement(
        MeasurementOutcome(
            terminal_state="answered",
            answer_generation_state="completed",
            assessment_state="completed",
            score=30,
            verdict="pass",
        )
    )
    incomplete = measured.record_presentation(
        run_record=PresentationGate(GateState.PASSED),
        prompt_assembly=PresentationGate(GateState.HELD, ("trace_not_captured",)),
        preparing_answer=PresentationGate(GateState.PASSED),
    )

    with pytest.raises(ValueError, match="failure class"):
        incomplete.classify(None)

    held = incomplete.classify(FailureClass.EVALUATION_CONTRACT_DEFECT)
    assert held.state is ImprovementState.HELD


def test_browser_observation_reduces_run_prompt_and_preparing_gates() -> None:
    measured = _validated().record_measurement(
        MeasurementOutcome(
            terminal_state="answered",
            answer_generation_state="completed",
            assessment_state="completed",
            score=30,
            verdict="pass",
        )
    )
    observation = BrowserRunObservation(
        run_id=measured.run_id,
        case_id=measured.case_id,
        question_fingerprint=measured.question_fingerprint,
        session_id=f"pantheon-assurance:{measured.run_id}",
        purpose=f"conversation-assurance:{measured.case_id}",
        request_sequence=1,
        request_sha256="sha256:" + "d" * 64,
        trace_receipt_digest="e" * 64,
        run_record_present=True,
        phase_states=tuple(
            (phase, "completed")
            for phase in ("input", "plan", "collaboration", "evidence", "verification", "answer")
        ),
        model_trace_enabled=True,
        omitted_model_calls=0,
        expected_call_kinds=("adaptive-plan", "adaptive-answer", "adaptive-review"),
        observed_call_kinds=("adaptive-plan", "adaptive-answer", "adaptive-review"),
        prompt_manifests_match=True,
        prompt_profiles_visible=True,
        system_layer_order_valid=True,
        untrusted_data_separated=True,
        preparing_answer_seen=True,
        early_answer_exposed=False,
        preparing_answer_overlapped_terminal=False,
        terminal_transition_completed=True,
        sensitive_output_detected=False,
    )

    completed = measured.record_browser_observation(observation).classify(None)
    assert completed.state is ImprovementState.COMPLETED


def test_browser_observation_fails_early_answer_and_incomplete_prompt_trace() -> None:
    observation = BrowserRunObservation(
        run_id="improvement-one",
        case_id="new-case-one",
        question_fingerprint="sha256:" + "a" * 64,
        session_id="pantheon-assurance:improvement-one",
        purpose="conversation-assurance:new-case-one",
        request_sequence=1,
        request_sha256="d" * 64,
        trace_receipt_digest="e" * 64,
        run_record_present=True,
        phase_states=(("input", "completed"),),
        model_trace_enabled=True,
        omitted_model_calls=1,
        expected_call_kinds=("adaptive-plan", "adaptive-answer"),
        observed_call_kinds=("adaptive-plan",),
        prompt_manifests_match=False,
        prompt_profiles_visible=False,
        system_layer_order_valid=False,
        untrusted_data_separated=False,
        preparing_answer_seen=True,
        early_answer_exposed=True,
        preparing_answer_overlapped_terminal=True,
        terminal_transition_completed=False,
        sensitive_output_detected=False,
    )

    reduced = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=30,
                verdict="pass",
            )
        )
        .record_browser_observation(observation)
    )
    assert reduced.run_record_gate.state is GateState.FAILED
    assert reduced.prompt_assembly_gate.state is GateState.FAILED
    assert "model_trace_stage_missing" in reduced.prompt_assembly_gate.reasons
    assert reduced.preparing_answer_gate.state is GateState.FAILED
    assert "answer_exposed_early" in reduced.preparing_answer_gate.reasons


def test_novelty_rejects_attempted_case_exact_and_lexical_duplicates() -> None:
    with pytest.raises(ValueError, match="already attempted"):
        validate_question_novelty(
            case_id="prior-case",
            question="Which current resources are unavailable?",
            campaign_rows=[{"attempted_case_ids": ["prior-case"]}],
            transcript_rows=[],
        )
    with pytest.raises(ValueError, match="lexically similar"):
        validate_question_novelty(
            case_id="fresh-case",
            question="Which current resources are unavailable right now",
            campaign_rows=[],
            transcript_rows=[
                {
                    "case_id": "old-case",
                    "question": "Which current resources are unavailable right now?",
                }
            ],
        )


def test_only_code_defects_enter_ten_round_hardening() -> None:
    measured = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=22,
                verdict="fail",
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.PASSED),
        )
    )
    unavailable = measured.classify(FailureClass.PROVIDER_OR_EVIDENCE_UNAVAILABLE)
    with pytest.raises(ValueError, match="only a code defect"):
        unavailable.record_hardening_round(FindingSeverity.NONE)

    run = measured.classify(FailureClass.CODE_DEFECT)
    for _ in range(9):
        run = run.record_hardening_round(FindingSeverity.NONE)
        assert run.state is ImprovementState.HARDENING
    run = run.record_hardening_round(FindingSeverity.LOW)
    assert run.state is ImprovementState.COMPLETED
    assert run.hardening_rounds == 10


def test_medium_finding_keeps_hardening_open_after_ten_rounds() -> None:
    run = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=20,
                verdict="fail",
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.FAILED, ("answer_exposed_early",)),
        )
        .classify(FailureClass.CODE_DEFECT)
    )

    for _ in range(10):
        run = run.record_hardening_round(FindingSeverity.MEDIUM)

    assert run.state is ImprovementState.HARDENING
    assert run.remaining_max_severity is FindingSeverity.MEDIUM


def test_hardening_completion_requires_passing_round_validation() -> None:
    run = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=20,
                verdict="fail",
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.FAILED, ("answer_exposed_early",)),
        )
        .classify(FailureClass.CODE_DEFECT)
    )
    for round_number in range(1, 11):
        run = run.record_hardening_round(
            FindingSeverity.NONE,
            reviewer_scope=f"review-{round_number}",
            validation_passed=round_number != 10,
        )

    assert run.state is ImprovementState.HARDENING
    assert run.hardening_history[-1].validation_passed is False


def test_incomplete_assessment_cannot_be_hardened_as_code() -> None:
    run = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="held",
                answer_generation_state="completed",
                assessment_state="deferred",
                assessment_reasons=("provider_http_429",),
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.PASSED),
        )
    )

    with pytest.raises(ValueError, match="incomplete assessment"):
        run.classify(FailureClass.CODE_DEFECT)


def test_external_completed_assessment_reason_cannot_be_hardened_as_code() -> None:
    run = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                assessment_reasons=("evaluator_response_invalid",),
                score=20,
                verdict="fail",
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.PASSED),
        )
    )

    with pytest.raises(ValueError, match="external or evaluation"):
        run.classify(FailureClass.CODE_DEFECT)


def test_prior_failed_round_validation_blocks_later_completion() -> None:
    run = (
        _validated()
        .record_measurement(
            MeasurementOutcome(
                terminal_state="answered",
                answer_generation_state="completed",
                assessment_state="completed",
                score=20,
                verdict="fail",
            )
        )
        .record_presentation(
            run_record=PresentationGate(GateState.PASSED),
            prompt_assembly=PresentationGate(GateState.PASSED),
            preparing_answer=PresentationGate(GateState.FAILED, ("answer_exposed_early",)),
        )
        .classify(FailureClass.CODE_DEFECT)
    )
    run = run.record_hardening_round(
        FindingSeverity.MEDIUM,
        reviewer_scope="review-one",
        finding_count=1,
        fixed_count=0,
        validation_passed=False,
    )
    for round_number in range(2, 11):
        run = run.record_hardening_round(
            FindingSeverity.NONE,
            reviewer_scope=f"review-{round_number}",
            validation_passed=True,
        )

    assert run.state is ImprovementState.HARDENING


def test_private_run_round_trips_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "state" / "run.json"
    run = _validated()

    write_private_run(path, run)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert read_private_run(path) == run


def test_private_run_rejects_missing_or_invalid_state_fields(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"run_id": "incomplete"}), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="state is invalid"):
        read_private_run(path)

    valid_path = tmp_path / "valid.json"
    write_private_run(valid_path, _validated())
    value = json.loads(valid_path.read_text(encoding="utf-8"))
    value["state"] = "unknown"
    valid_path.write_text(json.dumps(value), encoding="utf-8")
    valid_path.chmod(0o600)

    with pytest.raises(ValueError, match="state is invalid"):
        read_private_run(valid_path)

    unreachable_path = tmp_path / "unreachable.json"
    write_private_run(unreachable_path, _validated())
    unreachable = json.loads(unreachable_path.read_text(encoding="utf-8"))
    unreachable["state"] = "completed"
    unreachable_path.write_text(json.dumps(unreachable), encoding="utf-8")
    unreachable_path.chmod(0o600)

    with pytest.raises(ValueError, match="state is invalid"):
        read_private_run(unreachable_path)
