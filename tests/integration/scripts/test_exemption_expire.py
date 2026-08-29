"""Exemption auto-expiry + ahead-of-expiry alert CLI."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).parents[3]
_SCRIPT = _ROOT / "scripts/governance/exemption-expire.py"


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exemption_expire", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exemption(*, expires_at: str, state: str = "active") -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "id": "example.rule.rg-a",
        "rule_id": "example.rule",
        "scope": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-a",
        },
        "justification": "Waived while a migration is being completed for this scope.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approved_by": "00000000-0000-0000-0000-000000000002",
        "state": state,
        "created_at": "2026-08-01T00:00:00Z",
        "expires_at": expires_at,
    }
    return raw


def _write(directory: Path, name: str, payload: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _future(days: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).isoformat()


def _past(days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()


def test_missing_directory_is_a_no_op(cli: ModuleType, tmp_path: Path) -> None:
    assert cli.main([str(tmp_path / "missing")]) == 0


def test_dry_run_reports_expired_without_writing(
    cli: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "a.json", _exemption(expires_at=_past(1)))
    original = path.read_text(encoding="utf-8")

    assert cli.main([str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "would expire" in out
    assert path.read_text(encoding="utf-8") == original  # unchanged - dry-run


def test_apply_persists_expired_state(cli: ModuleType, tmp_path: Path) -> None:
    path = _write(tmp_path, "a.json", _exemption(expires_at=_past(1)))

    assert cli.main([str(tmp_path), "--apply"]) == 0

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["state"] == "expired"


def test_ahead_of_expiry_alert_is_reported(
    cli: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "a.json", _exemption(expires_at=_future(5)))

    assert cli.main([str(tmp_path), "--alert-lead-days", "14"]) == 0

    out = capsys.readouterr().out
    assert "ahead-of-expiry" in out
    assert "example.rule.rg-a" in out


def test_far_from_expiry_is_not_alerted(
    cli: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "a.json", _exemption(expires_at=_future(400)))

    assert cli.main([str(tmp_path), "--alert-lead-days", "14"]) == 0

    out = capsys.readouterr().out
    assert "ahead-of-expiry: 0 exemption" in out


def test_no_alerts_flag_skips_the_alert_pass(
    cli: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "a.json", _exemption(expires_at=_future(5)))

    assert cli.main([str(tmp_path), "--alert-lead-days", "14", "--no-alerts"]) == 0

    out = capsys.readouterr().out
    assert "ahead-of-expiry" not in out
