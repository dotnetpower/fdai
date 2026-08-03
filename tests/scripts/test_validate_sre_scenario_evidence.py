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
    return {
        "status": status,
        "target": "synthetic-target",
        "time_window": {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T00:01:00Z",
        },
        "injection_evidence": {"summary": "Bounded action observed", "source": "test"},
        "detection_evidence": {"summary": "Expected signal observed", "source": "test"},
        "root_cause": {"summary": "Synthetic cause", "source": "test"},
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
            "status": recovery_status,
            "summary": "Terminal state observed",
            "source": "test",
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
        "scenarios": {f"S{index}": _scenario() for index in range(1, 15)},
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
    assert "scenarios.S5 MUST NOT be passed without terminal recovery evidence" in errors


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
    assert "scenarios.S9.cleanup.residuals MUST be empty" in errors
    assert "scenarios.S9.unsupported_claims MUST be empty" in errors
