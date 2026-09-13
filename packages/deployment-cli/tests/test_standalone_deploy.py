from __future__ import annotations

import subprocess

import pytest

from fdai_deployment_cli import cli, standalone_deploy
from fdai_deployment_cli.standalone_deploy import _standalone_subprocess_environment


def test_standalone_subprocess_environment_drops_ambient_secrets() -> None:
    result = _standalone_subprocess_environment(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/operator",
            "AZURE_CONFIG_DIR": "/home/operator/.azure",
            "ARM_CLIENT_SECRET": "do-not-copy",
            "AZURE_CLIENT_SECRET": "do-not-copy",
            "GITHUB_TOKEN": "do-not-copy",
            "GH_TOKEN": "do-not-copy",
        },
        AZURE_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000001",
    )

    assert result == {
        "PATH": "/usr/bin",
        "HOME": "/home/operator",
        "AZURE_CONFIG_DIR": "/home/operator/.azure",
        "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
    }


@pytest.mark.parametrize("failure", ["timeout", "filesystem"])
def test_azure_read_failure_never_discloses_private_command_or_path(monkeypatch, capsys, failure):
    def failed(*_args, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(["az", "private-target-marker"], 60)
        raise FileNotFoundError(2, "private-provider-marker", "/private-path-marker")

    monkeypatch.setattr(standalone_deploy.subprocess, "run", failed)
    assert cli.main(["provision", "azure", "--online", "--progress", "off"]) == 3
    captured = capsys.readouterr()
    assert "private-" not in captured.err
    assert captured.out == ""


def test_operator_id_timeout_is_value_safe(monkeypatch):
    def failed(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["az", "private-operator-marker"], 60)

    monkeypatch.setattr(standalone_deploy.subprocess, "run", failed)
    with pytest.raises(ValueError, match="operator") as error:
        standalone_deploy._current_operator_object_id()
    assert "private-" not in str(error.value)


@pytest.mark.parametrize("error_type", [OSError, subprocess.SubprocessError])
def test_cli_raw_failure_fallback_is_value_safe(monkeypatch, capsys, error_type):
    def failed(**_kwargs):
        raise error_type("private-fallback-marker")

    monkeypatch.setattr(cli, "deploy_azure_foundation", failed)
    assert cli.main(["provision", "azure", "--online", "--progress", "off"]) == 3
    captured = capsys.readouterr()
    assert "private-" not in captured.err
    assert "inspect retained evidence" in captured.err
    assert captured.out == ""
