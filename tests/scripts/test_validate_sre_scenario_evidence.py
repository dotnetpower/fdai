"""Regression tests for the S1-S14 evidence ledger validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "quality"
    / "repository"
    / "validate-sre-scenario-evidence.py"
)


@pytest.fixture(scope="module")
def validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_sre_scenario_evidence", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scenario(status: str = "passed") -> dict[str, object]:
    recovery_status = "not-applicable" if status == "not-applicable" else "verified"
    receipt = {
        "summary": "Expected state observed",
        "authority_class": "synthetic-test",
        "source_identity": "test-observer",
        "scope": "one synthetic target",
        "purpose": "contract regression",
        "query_version": "test-v1",
        "event_time": "2026-01-01T00:00:30Z",
        "recorded_at": "2026-01-01T00:00:31Z",
        "freshness": "current for test window",
        "completeness": "complete synthetic fixture",
        "provenance_digest": "a" * 64,
        "synthetic": False,
    }
    return {
        "status": status,
        "target": "synthetic-target",
        "time_window": {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T00:01:00Z",
        },
        "injection_evidence": {**receipt, "summary": "Bounded action observed"},
        "detection_evidence": {**receipt, "summary": "Expected signal observed"},
        "root_cause": {
            "summary": "Synthetic cause",
            "confidence": "high",
            "alternatives": [],
        },
        "measurements": [
            {
                "name": "sample",
                "value": 1,
                "unit": "count",
                "source": "test",
                "observed_at": "2026-01-01T00:00:30Z",
            }
        ],
        "recovery_evidence": {
            **receipt,
            "status": recovery_status,
            "summary": "Terminal state observed",
        },
        "safety": {
            "approval": "Synthetic approval",
            "blast_radius": "One synthetic target",
            "stop_condition": "One minute",
            "rollback": "Restore synthetic state",
        },
        "cleanup": {"status": "verified", "residuals": []},
        "unsupported_claims": [],
    }


def _ledger() -> dict[str, object]:
    scenarios = {f"S{index}": _scenario() for index in range(1, 15)}
    for scenario_id in ("S13", "S14"):
        recovery = scenarios[scenario_id]["recovery_evidence"]
        cleanup = scenarios[scenario_id]["cleanup"]
        assert isinstance(recovery, dict) and isinstance(cleanup, dict)
        recovery["status"] = "not-applicable"
        cleanup["status"] = "not-applicable"
    return {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:02:00Z",
        "summary": {
            "passed": 14,
            "partial": 0,
            "blocked": 0,
            "failed": 0,
            "not-applicable": 0,
        },
        "scenarios": scenarios,
    }


def test_complete_ledger_passes(validator: ModuleType) -> None:
    assert validator.validate(_ledger()) == []


def test_status_only_legacy_shape_fails_closed(validator: ModuleType) -> None:
    legacy = {
        "summary": {"s1_s12_passed": 8},
        "scenarios": {f"S{index}": "passed" for index in range(1, 15)},
    }
    errors = validator.validate(legacy)
    assert "schema_version MUST equal 1" in errors
    assert "generated_at MUST be an RFC 3339 UTC timestamp ending in Z" in errors
    assert "scenarios.S1 MUST be an object" in errors


@pytest.mark.parametrize("status", ["passed-adapted", "unknown"])
def test_non_contract_verdict_fails(validator: ModuleType, status: str) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S6"]
    assert isinstance(scenario, dict)
    scenario["status"] = status
    errors = validator.validate(ledger)
    assert any("scenarios.S6.status MUST be one of" in error for error in errors)


def test_passed_requires_terminal_recovery(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S5"]
    assert isinstance(scenario, dict)
    recovery = scenario["recovery_evidence"]
    assert isinstance(recovery, dict)
    recovery["status"] = "not-run"
    errors = validator.validate(ledger)
    assert "scenarios.S5 passed status requires recovery_evidence.status=verified" in errors


def test_summary_and_time_order_are_reconciled(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S8"]
    assert isinstance(scenario, dict)
    scenario["status"] = "blocked"
    window = scenario["time_window"]
    assert isinstance(window, dict)
    window["end"] = "2025-12-31T23:59:59Z"
    errors = validator.validate(ledger)
    assert "summary.passed MUST equal observed scenario count 13" in errors
    assert "summary.blocked MUST equal observed scenario count 1" in errors
    assert "scenarios.S8.time_window.end MUST not precede start" in errors


def test_cleanup_and_unsupported_claims_fail_closed(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S9"]
    assert isinstance(scenario, dict)
    cleanup = scenario["cleanup"]
    assert isinstance(cleanup, dict)
    cleanup["residuals"] = ["worker"]
    scenario["unsupported_claims"] = ["Unverified success"]
    errors = validator.validate(ledger)
    assert "scenarios.S9.cleanup.residuals MUST be empty for passed status" in errors
    assert "scenarios.S9.unsupported_claims MUST be empty" in errors


def test_partial_scenario_preserves_cleanup_residuals(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    summary = ledger["summary"]
    assert isinstance(scenarios, dict) and isinstance(summary, dict)
    scenario = scenarios["S11"]
    assert isinstance(scenario, dict)
    scenario["status"] = "partial"
    cleanup = scenario["cleanup"]
    assert isinstance(cleanup, dict)
    cleanup["status"] = "incomplete"
    cleanup["residuals"] = ["Current replica state requires reconciliation"]
    summary["passed"] = 13
    summary["partial"] = 1
    assert validator.validate(ledger) == []


def test_decision_evidence_requires_replayable_provenance(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S1"]
    assert isinstance(scenario, dict)
    evidence = scenario["detection_evidence"]
    assert isinstance(evidence, dict)
    del evidence["source_identity"]
    evidence["provenance_digest"] = "not-a-digest"
    evidence["synthetic"] = "false"
    errors = validator.validate(ledger)
    assert "scenarios.S1.detection_evidence.source_identity MUST be non-empty text" in errors
    assert (
        "scenarios.S1.detection_evidence.provenance_digest MUST be a lowercase SHA-256 digest"
        in errors
    )
    assert "scenarios.S1.detection_evidence.synthetic MUST be a boolean" in errors


def test_synthetic_evidence_cannot_close_passed_live_scenario(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S1"]
    assert isinstance(scenario, dict)
    evidence = scenario["detection_evidence"]
    assert isinstance(evidence, dict)
    evidence["synthetic"] = True
    errors = validator.validate(ledger)
    assert "scenarios.S1 MUST NOT be passed using synthetic decision evidence" in errors


def test_only_non_fault_scenarios_allow_inapplicable_recovery(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    fault = scenarios["S1"]
    non_fault = scenarios["S13"]
    assert isinstance(fault, dict) and isinstance(non_fault, dict)
    fault_recovery = fault["recovery_evidence"]
    non_fault_recovery = non_fault["recovery_evidence"]
    assert isinstance(fault_recovery, dict) and isinstance(non_fault_recovery, dict)
    fault_recovery["status"] = "not-applicable"
    non_fault_recovery["status"] = "not-applicable"
    non_fault_cleanup = non_fault["cleanup"]
    assert isinstance(non_fault_cleanup, dict)
    non_fault_cleanup["status"] = "not-applicable"
    errors = validator.validate(ledger)
    assert "scenarios.S1 passed status requires recovery_evidence.status=verified" in errors
    assert not any(error.startswith("scenarios.S13") for error in errors)


def test_receipt_and_measurement_chronology_is_ordered(validator: ModuleType) -> None:
    ledger = _ledger()
    scenarios = ledger["scenarios"]
    assert isinstance(scenarios, dict)
    scenario = scenarios["S3"]
    assert isinstance(scenario, dict)
    evidence = scenario["detection_evidence"]
    measurements = scenario["measurements"]
    assert isinstance(evidence, dict) and isinstance(measurements, list)
    evidence["event_time"] = "2026-01-01T00:00:45Z"
    evidence["recorded_at"] = "2026-01-01T00:00:44Z"
    measurement = measurements[0]
    assert isinstance(measurement, dict)
    measurement["observed_at"] = "2025-12-31T23:59:59Z"
    errors = validator.validate(ledger)
    assert "scenarios.S3.detection_evidence.recorded_at MUST not precede event_time" in errors
    assert (
        "scenarios.S3.measurements[0].observed_at MUST be inside the scenario time_window" in errors
    )
