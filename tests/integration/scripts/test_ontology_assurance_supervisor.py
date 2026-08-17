from __future__ import annotations

import asyncio
import json
import signal
import stat
import sys
from pathlib import Path

import pytest
from scripts.automation.ontology_assurance_supervisor import (
    AssuranceProcessSupervisor,
    AtomicRunStatus,
    ProcessSpec,
    RequiredChildExitedError,
)
from scripts.automation.run_ontology_assurance import (
    full_artifact_accepted,
    strict_artifact_accepted,
)

SOURCE_REVISION = "a" * 40


def _spec(
    tmp_path: Path,
    label: str,
    code: str,
    *,
    environment: dict[str, str] | None = None,
) -> ProcessSpec:
    return ProcessSpec(
        label=label,
        command=(sys.executable, "-c", code),
        command_label=f"test:{label}",
        cwd=tmp_path,
        log_path=tmp_path / "logs" / f"{label}.log",
        environment=environment,
    )


def test_required_child_exit_stops_the_measured_process_group(tmp_path: Path) -> None:
    async def exercise() -> None:
        status = AtomicRunStatus(
            tmp_path / "status.json",
            run_id="issue63-supervision-test",
            source_revision=SOURCE_REVISION,
        )
        supervisor = AssuranceProcessSupervisor(status, stop_timeout_seconds=1.0)
        try:
            await supervisor.start_services((_spec(tmp_path, "core", "raise SystemExit(23)"),))
            with pytest.raises(RequiredChildExitedError) as raised:
                await supervisor.run_phase(
                    _spec(tmp_path, "strict_14", "import signal; signal.pause()")
                )

            assert raised.value.process_exit.label == "core"
            assert raised.value.process_exit.exit_code == 23
            assert raised.value.process_exit.signal_name is None
        finally:
            await supervisor.close()

    asyncio.run(exercise())

    status_path = tmp_path / "status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["source_revision"] == SOURCE_REVISION
    assert payload["termination"] == {
        "reason": "required_child_exited",
        "child": "core",
        "exit_code": 23,
        "signal": None,
    }
    assert payload["processes"]["core"]["exit_code"] == 23
    assert payload["processes"]["core"]["process_group_id"] > 0
    assert payload["processes"]["strict_14"]["signal"] == signal.Signals.SIGTERM.name
    assert payload["processes"]["strict_14"]["termination_request"] == "required_child_exited"
    assert stat.S_IMODE(status_path.stat().st_mode) == 0o600


def test_phase_exit_does_not_hide_running_service_provenance(tmp_path: Path) -> None:
    async def exercise() -> int:
        status = AtomicRunStatus(
            tmp_path / "status.json",
            run_id="issue63-phase-test",
            source_revision=SOURCE_REVISION,
        )
        supervisor = AssuranceProcessSupervisor(status, stop_timeout_seconds=1.0)
        try:
            await supervisor.start_services(
                (_spec(tmp_path, "operator", "import signal; signal.pause()"),)
            )
            phase_exit = await supervisor.run_phase(
                _spec(tmp_path, "strict_14", "raise SystemExit(7)")
            )
            return phase_exit.returncode
        finally:
            await supervisor.close("phase_complete")

    assert asyncio.run(exercise()) == 7
    payload = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert payload["processes"]["strict_14"]["exit_code"] == 7
    assert payload["processes"]["operator"]["pid"] > 0
    assert payload["processes"]["operator"]["process_group_id"] > 0
    assert payload["processes"]["operator"]["termination_request"] == "phase_complete"


def test_readiness_guard_fails_closed_when_a_required_child_exits(tmp_path: Path) -> None:
    async def exercise() -> None:
        status = AtomicRunStatus(
            tmp_path / "status.json",
            run_id="issue63-readiness-test",
            source_revision=SOURCE_REVISION,
        )
        supervisor = AssuranceProcessSupervisor(status, stop_timeout_seconds=1.0)
        try:
            await supervisor.start_services((_spec(tmp_path, "core", "raise SystemExit(31)"),))
            with pytest.raises(RequiredChildExitedError) as raised:
                await supervisor.guard_operation(asyncio.Event().wait(), timeout_seconds=10.0)
            assert raised.value.process_exit.exit_code == 31
        finally:
            await supervisor.close()

    asyncio.run(exercise())
    payload = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert payload["termination"]["reason"] == "required_child_exited"


def _passing_artifact(question_count: int) -> dict[str, object]:
    summary: dict[str, object] = {
        "question_count": question_count,
        "live_question_count": question_count,
        "resumed_question_count": 0,
        "passed_count": question_count,
        "answered_count": question_count,
        "answered_with_complete_evidence_count": question_count,
        "evidence_generation_consistent": True,
        "answered_locale_coverage_complete": True,
        "transport_retry_count": 0,
        "exhausted_transport_retry_count": 0,
        "unsupported_operational_claim_count": 0,
        "unauthorized_execution_count": 0,
        "plan_capability_mismatch_count": 0,
    }
    if question_count == 14:
        summary.update(
            locale_counts={"en": 7, "ko": 7},
            operation_counts={
                "aggregation": 2,
                "causal_analysis": 2,
                "evidence_validation": 2,
                "inventory_listing": 2,
                "property_filter": 2,
                "relationship_traversal": 2,
                "temporal_comparison": 2,
            },
        )
    else:
        summary.update(
            locale_coverage_complete=True,
            operation_coverage_complete=True,
            required_answer_coverage_complete=True,
        )
    return {
        "schema_version": "1.3.0",
        "source_revision": SOURCE_REVISION,
        "passed": True,
        "production_ready": question_count == 100,
        "run_mode": "live",
        "receipt_source": "live_assurance",
        "run_configuration": {"schema_version": "1.4.0"},
        "summary": summary,
    }


def test_strict_gate_rejects_resumed_or_incomplete_evidence() -> None:
    passing = _passing_artifact(14)
    assert strict_artifact_accepted(passing, SOURCE_REVISION)

    resumed = json.loads(json.dumps(passing))
    resumed["summary"]["resumed_question_count"] = 1
    assert not strict_artifact_accepted(resumed, SOURCE_REVISION)

    incomplete = json.loads(json.dumps(passing))
    incomplete["summary"]["answered_with_complete_evidence_count"] = 13
    assert not strict_artifact_accepted(incomplete, SOURCE_REVISION)


def test_seeded_gate_requires_fresh_complete_production_evidence() -> None:
    passing = _passing_artifact(100)
    assert full_artifact_accepted(passing, SOURCE_REVISION)

    resumed = json.loads(json.dumps(passing))
    resumed["summary"]["live_question_count"] = 99
    resumed["summary"]["resumed_question_count"] = 1
    assert not full_artifact_accepted(resumed, SOURCE_REVISION)

    unsafe = json.loads(json.dumps(passing))
    unsafe["summary"]["unauthorized_execution_count"] = 1
    assert not full_artifact_accepted(unsafe, SOURCE_REVISION)


def test_child_environment_is_not_retained_in_status(tmp_path: Path) -> None:
    async def exercise() -> None:
        status = AtomicRunStatus(
            tmp_path / "status.json",
            run_id="issue63-environment-test",
            source_revision=SOURCE_REVISION,
        )
        supervisor = AssuranceProcessSupervisor(status, stop_timeout_seconds=1.0)
        try:
            phase_exit = await supervisor.run_phase(
                _spec(
                    tmp_path,
                    "strict_14",
                    "import os; print(os.environ['PRIVATE_ASSURANCE_TEST_VALUE'])",
                    environment={"PRIVATE_ASSURANCE_TEST_VALUE": "must-not-be-retained"},
                )
            )
            assert phase_exit.returncode == 0
        finally:
            await supervisor.close()

    asyncio.run(exercise())
    status_text = (tmp_path / "status.json").read_text(encoding="utf-8")
    assert "must-not-be-retained" not in status_text
    assert "PRIVATE_ASSURANCE_TEST_VALUE" not in status_text
    assert "must-not-be-retained" in (tmp_path / "logs" / "strict_14.log").read_text()
