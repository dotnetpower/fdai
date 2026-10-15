"""Typed state reductions shared by conversation-improvement operations."""

from __future__ import annotations

from pathlib import Path

from fdai.core.conversation_assurance import open_private_lock
from scripts.automation.conversation_assurance_harness import (
    FailureClass,
    GateState,
    ImprovementRun,
    read_private_run,
    write_private_run,
)


def automatic_failure_class(run: ImprovementRun) -> FailureClass | None:
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


def classify_run(
    *,
    run_path: Path,
    lock_path: Path,
    failure_class: FailureClass | None,
) -> ImprovementRun:
    lock = open_private_lock(lock_path)
    if lock is None:
        raise ValueError("improvement_run_active")
    with lock:
        classified = read_private_run(run_path).classify(failure_class)
        write_private_run(run_path, classified)
        return classified


def bounded_reason(error: Exception) -> str:
    value = str(error)
    return value if value and len(value) <= 128 else f"measurement_error:{type(error).__name__}"


__all__ = ["automatic_failure_class", "bounded_reason", "classify_run"]
