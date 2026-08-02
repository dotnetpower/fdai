"""Security posture audit checks and narrow permission fixes."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from fdai.deployment_cli.security_audit import run_security_audit


def test_non_dev_auth_bypass_and_missing_entra_are_critical() -> None:
    report = run_security_audit(env={"RUNTIME_ENV": "prod", "FDAI_OPERATOR_API_DEV_MODE": "1"})

    assert report.secure is False
    assert {finding.check_id for finding in report.findings} == {
        "auth.dev-bypass-non-dev",
        "auth.entra-config-missing",
    }


def test_enforce_misconfiguration_fails_closed_without_values() -> None:
    report = run_security_audit(
        env={
            "RUNTIME_ENV": "dev",
            "FDAI_VM_TASK_ENFORCE": "1",
            "FDAI_CHAOS_ENFORCE": "1",
        }
    )

    rendered = report.to_json()
    assert report.secure is False
    assert "execution.vm-task-enforce-without-enable" in rendered
    assert "execution.chaos-context-missing" in rendered


def test_missing_requested_bubblewrap_is_critical() -> None:
    report = run_security_audit(
        env={"FDAI_COMMAND_RUNNER": "bubblewrap"},
        resolve_executable=lambda _: None,
    )

    assert report.secure is False
    assert report.findings[0].check_id == "sandbox.bubblewrap-missing"


def test_config_permissions_are_fixed_narrowly(tmp_path: Path) -> None:
    directory = tmp_path / "config"
    directory.mkdir(mode=0o755)
    path = directory / "dev.json"
    path.write_text(json.dumps({"environment": "dev"}), encoding="utf-8")
    path.chmod(0o644)

    report = run_security_audit(config_path=path, env={}, fix_permissions=True)

    assert report.secure is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(finding.fixed for finding in report.findings)


def test_secret_like_config_key_remains_critical(tmp_path: Path) -> None:
    path = tmp_path / "dev.json"
    path.write_text(json.dumps({"api_token": "not-printed"}), encoding="utf-8")
    path.chmod(0o600)

    report = run_security_audit(config_path=path, env={})

    assert report.secure is False
    assert "not-printed" not in report.to_json()
    assert any(finding.check_id == "config.secret-like-key" for finding in report.findings)


def test_symlink_config_is_never_fixed(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "config.json"
    link.symlink_to(target)

    report = run_security_audit(config_path=link, env={}, fix_permissions=True)

    assert report.secure is False
    assert report.findings[0].check_id == "config.symlink"
    assert link.is_symlink()
