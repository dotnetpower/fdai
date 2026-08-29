from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli.plan_input import PLAN_ONLY_PASSWORD, snapshot_plan_input


def _values() -> dict[str, str]:
    return {
        "region": "koreacentral",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "postgres_admin_login": "fdaiadmin",
        "postgres_admin_password": PLAN_ONLY_PASSWORD,
        "core_image": "ghcr.io/example/fdai:plan-only",
    }


def _write(path: Path, values: dict[str, str]) -> None:
    path.write_text(json.dumps(values), encoding="utf-8")
    path.chmod(0o600)


def test_plan_input_is_private_canonical_and_non_secret(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    destination = tmp_path / "snapshot.json"
    _write(source, _values())

    snapshot_plan_input(source, destination)

    assert destination.stat().st_mode & 0o777 == 0o600
    assert json.loads(destination.read_text(encoding="utf-8")) == _values()


def test_plan_input_rejects_real_password_and_extra_secret(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    values = _values()
    values["postgres_admin_password"] = "a-real-password-value"
    _write(source, values)
    with pytest.raises(ValueError, match="plan-only password"):
        snapshot_plan_input(source, tmp_path / "snapshot.json")

    values = _values()
    values["alert_webhook_url"] = "https://example.com/credential"
    _write(source, values)
    with pytest.raises(ValueError, match="secret-free schema"):
        snapshot_plan_input(source, tmp_path / "snapshot.json")


def test_plan_input_requires_private_regular_source(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    _write(source, _values())
    source.chmod(0o644)
    with pytest.raises(PermissionError, match="mode-0600"):
        snapshot_plan_input(source, tmp_path / "snapshot.json")
