"""Focused tests for the installable deployment CLI."""

from __future__ import annotations

import io
import json
import stat
from importlib.metadata import version
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import VERSION_SCHEMA, main
from fdai.deployment_cli.doctor import DOCTOR_SCHEMA, run_doctor
from fdai.deployment_cli.onboarding import (
    CONFIG_SCHEMA,
    OnboardingError,
    initialize_environment,
    load_environment,
)

_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
_TENANT_ID = "00000000-0000-0000-0000-000000000002"
_CLI_VERSION = version("fdai")


def test_version_json_is_stable_and_machine_readable() -> None:
    stdout = io.StringIO()

    exit_code = main(["version", "--output", "json"], stdout=stdout)

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {
        "bundle_version": "not-installed",
        "cli_version": _CLI_VERSION,
        "schema": VERSION_SCHEMA,
    }


def test_version_text_is_concise() -> None:
    stdout = io.StringIO()

    exit_code = main(["version"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == f"FDAI CLI {_CLI_VERSION} (bundle: not-installed)\n"


def test_doctor_json_is_secret_free_and_ready() -> None:
    executables = {name: f"/tools/{name}" for name in ("az", "terraform", "gh")}
    report = run_doctor(
        resolve_executable=executables.get,
        run_command=lambda _: json.dumps(
            {
                "id": "subscription-sensitive",
                "state": "Enabled",
                "tenantId": "tenant-sensitive",
                "user": {"name": "operator-sensitive", "type": "user"},
            }
        ),
    )

    rendered = report.to_json()

    assert report.ready is True
    assert json.loads(rendered)["schema"] == DOCTOR_SCHEMA
    assert "sensitive" not in rendered


def test_doctor_fails_closed_when_tool_and_auth_are_unavailable() -> None:
    report = run_doctor(resolve_executable=lambda _: None)

    assert report.ready is False
    assert {check.check_id for check in report.checks if check.status == "fail"} == {
        "tool.az",
        "tool.terraform",
        "tool.gh",
        "azure.auth",
    }


def test_doctor_rejects_service_principal_context() -> None:
    executables = {name: f"/tools/{name}" for name in ("az", "terraform", "gh")}
    report = run_doctor(
        resolve_executable=executables.get,
        run_command=lambda _: json.dumps(
            {"state": "Enabled", "user": {"type": "servicePrincipal"}}
        ),
    )

    assert report.ready is False
    assert next(check for check in report.checks if check.check_id == "azure.auth").status == "fail"


def test_doctor_rejects_active_account_mismatch_without_leaking_ids(tmp_path: Path) -> None:
    destination = tmp_path / "dev.json"
    initialize_environment(
        environment="dev",
        region="koreacentral",
        destination=destination,
        run_command=_account_runner,
        resolve_executable=lambda _: "/tools/az",
    )
    executables = {name: f"/tools/{name}" for name in ("az", "terraform", "gh")}

    report = run_doctor(
        config_path=destination,
        resolve_executable=executables.get,
        run_command=lambda _: json.dumps(
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "state": "Enabled",
                "tenantId": _TENANT_ID,
                "user": {"type": "user"},
            }
        ),
    )

    rendered = report.to_json()
    assert report.ready is False
    target_check = next(check for check in report.checks if check.check_id == "azure.target")
    assert target_check.status == "fail"
    assert _SUBSCRIPTION_ID not in rendered
    assert "00000000-0000-0000-0000-000000000003" not in rendered


def test_doctor_accepts_matching_active_account(tmp_path: Path) -> None:
    destination = tmp_path / "dev.json"
    initialize_environment(
        environment="dev",
        region="koreacentral",
        destination=destination,
        run_command=_account_runner,
        resolve_executable=lambda _: "/tools/az",
    )
    executables = {name: f"/tools/{name}" for name in ("az", "terraform", "gh")}

    report = run_doctor(
        config_path=destination,
        resolve_executable=executables.get,
        run_command=_account_runner,
    )

    assert report.ready is True


def test_cli_doctor_returns_incomplete_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fdai.deployment_cli.cli.run_doctor",
        lambda **_: run_doctor(resolve_executable=lambda _: None),
    )
    stdout = io.StringIO()

    exit_code = main(["doctor", "--output", "json"], stdout=stdout)

    assert exit_code == 4
    assert json.loads(stdout.getvalue())["ready"] is False


def _account_runner(_: tuple[str, ...]) -> str:
    return json.dumps(
        {
            "id": _SUBSCRIPTION_ID,
            "state": "Enabled",
            "tenantId": _TENANT_ID,
            "user": {"name": "operator@example.com", "type": "user"},
        }
    )


def test_onboard_init_writes_valid_private_config(tmp_path: Path) -> None:
    destination = tmp_path / "dev.json"

    result = initialize_environment(
        environment="dev",
        region="koreacentral",
        destination=destination,
        run_command=_account_runner,
        resolve_executable=lambda _: "/tools/az",
    )

    config = load_environment(destination)
    assert result.path == str(destination)
    assert config.schema_version == CONFIG_SCHEMA
    assert str(config.azure.subscription_id) == _SUBSCRIPTION_ID
    assert config.execution_target == "remote-runner"
    assert config.autonomy_mode_default == "shadow"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_onboard_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    destination = tmp_path / "dev.json"
    destination.write_text("existing", encoding="utf-8")

    with pytest.raises(OnboardingError, match="already exists"):
        initialize_environment(
            environment="dev",
            region="koreacentral",
            destination=destination,
            run_command=_account_runner,
            resolve_executable=lambda _: "/tools/az",
        )

    assert destination.read_text(encoding="utf-8") == "existing"


def test_onboard_init_rejects_invalid_region_without_creating_file(tmp_path: Path) -> None:
    destination = tmp_path / "dev.json"

    with pytest.raises(OnboardingError, match="invalid"):
        initialize_environment(
            environment="dev",
            region="not a region",
            destination=destination,
            run_command=_account_runner,
            resolve_executable=lambda _: "/tools/az",
        )

    assert not destination.exists()
