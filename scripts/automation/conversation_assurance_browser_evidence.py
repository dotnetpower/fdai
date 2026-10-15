"""Strict content-free browser evidence parsing for conversation assurance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scripts.automation.conversation_assurance_harness import (
    BrowserRunObservation,
    MeasurementOutcome,
)


def browser_observation(value: Mapping[str, Any]) -> BrowserRunObservation:
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


def terminal_measurement_outcome(value: Mapping[str, object]) -> MeasurementOutcome:
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


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("browser_observation_invalid")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("browser_observation_invalid")
    return tuple(value)


__all__ = ["browser_observation", "terminal_measurement_outcome"]
