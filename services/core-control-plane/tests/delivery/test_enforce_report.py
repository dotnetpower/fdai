from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.chaos.enforce_report import load_enforce_report


def _run() -> dict[str, object]:
    return {
        "approval_ref": "approval:test-sweep",
        "detected": True,
        "elapsed_seconds": 2.5,
        "ended_at": "2026-09-21T11:02:03+00:00",
        "error": None,
        "expected_signal": "pod_restart",
        "experiment_id": "chaos-example",
        "injected": True,
        "mode": "enforce",
        "outcome": "validated",
        "reverted": True,
        "scenario_id": "aks-pod-kill",
        "started_at": "2026-09-21T11:02:00+00:00",
        "stop_reason": None,
        "stopped": True,
        "targets": ["app=example"],
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_loads_authoritative_enforce_result_as_structured_signal(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write(report, {"runs": [_run()]})

    signals = load_enforce_report(report)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_id == "chaos-example"
    assert signal.title == "chaos aks-pod-kill: validated"
    assert signal.metadata == {
        "scenario_id": "aks-pod-kill",
        "outcome": "validated",
        "mode": "enforce",
        "expected_signal": "pod_restart",
        "detected": "true",
        "reverted": "true",
        "injected": "true",
        "stopped": "true",
        "approval_ref": "approval:test-sweep",
    }


def test_rejects_conflicting_derived_rollback_value(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    run = _run()
    run["reverted"] = False
    _write(report, {"runs": [run]})

    with pytest.raises(ValueError, match="reverted value conflicts"):
        load_enforce_report(report)


def test_rejects_symlinked_report(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    report = tmp_path / "report.json"
    _write(target, {"runs": [_run()]})
    report.symlink_to(target)

    with pytest.raises(ValueError, match="non-symlink"):
        load_enforce_report(report)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("started_at", "not-a-timestamp", "must be RFC 3339"),
        ("ended_at", "2026-09-21T11:01:59+00:00", "timestamps are reversed"),
        ("elapsed_seconds", -1, "must be non-negative"),
        ("approval_ref", "a" * 257, "exceeds the supported bound"),
    ],
)
def test_rejects_invalid_bounded_run_values(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    report = tmp_path / "report.json"
    run = _run()
    run[field] = value
    _write(report, {"runs": [run]})

    with pytest.raises(ValueError, match=message):
        load_enforce_report(report)


def test_rejects_missing_run_field(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    run = _run()
    del run["expected_signal"]
    _write(report, {"runs": [run]})

    with pytest.raises(ValueError, match="fields do not match"):
        load_enforce_report(report)


def test_rejects_duplicate_json_key(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"runs": [], "runs": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key: runs"):
        load_enforce_report(report)


def test_rejects_oversized_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(b" " * 1_048_577)

    with pytest.raises(ValueError, match="size is outside"):
        load_enforce_report(report)


def test_rejects_unbounded_run_count(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write(report, {"runs": [_run()] * 257})

    with pytest.raises(ValueError, match="bounded array"):
        load_enforce_report(report)
