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


def _new_aks_installation(monkeypatch, tmp_path, preflight):
    events: list[str] = []
    monkeypatch.setattr(
        standalone_deploy,
        "active_azure_target",
        lambda: standalone_deploy.ActiveAzureTarget(
            subscription_id="00000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000002",
        ),
    )
    monkeypatch.setattr(standalone_deploy, "acquire_deployment_kit", lambda **_kwargs: object())
    monkeypatch.setattr(standalone_deploy, "deploy_with_adopted_foundation", lambda **_kwargs: None)

    def inspect(**kwargs):
        events.append(f"preflight:{kwargs['region']}")
        return preflight

    def discovery(stage):
        events.append(f"stage:{stage}")
        if stage == "discovery":
            raise RuntimeError("stop-at-discovery")

    monkeypatch.setattr(standalone_deploy, "inspect_aks_target", inspect)
    monkeypatch.setattr(standalone_deploy, "begin_stage", discovery)

    def invoke():
        return standalone_deploy.deploy_azure_foundation(
            work_dir=tmp_path / "work",
            online=False,
            offline_kit=tmp_path / "kit.tar.gz",
            online_url=None,
            region="westus2",
            monthly_cost_ceiling=2000,
            timeout_seconds=3600,
            trial_token=None,
            runtime_profile=standalone_deploy.RuntimeDeploymentProfile.create(
                runtime_platform="aks", database_placement="postgres-flex"
            ),
        )

    return invoke, events


def test_new_aks_installation_stops_on_preflight_blockers_before_discovery(
    monkeypatch, tmp_path
) -> None:
    invoke, events = _new_aks_installation(
        monkeypatch,
        tmp_path,
        {"state": "blocked", "blockers": ["postgres_flex_region_restricted"]},
    )

    with pytest.raises(ValueError, match="preflight blocked a new installation: postgres_flex"):
        invoke()

    assert events == ["stage:azure", "stage:kit", "preflight:westus2"]


def test_feasible_new_aks_installation_continues_to_discovery(monkeypatch, tmp_path) -> None:
    invoke, events = _new_aks_installation(
        monkeypatch, tmp_path, {"state": "feasible", "blockers": []}
    )

    with pytest.raises(RuntimeError, match="stop-at-discovery"):
        invoke()

    assert events == ["stage:azure", "stage:kit", "preflight:westus2", "stage:discovery"]


def test_resumed_aks_installation_skips_the_new_installation_preflight(
    monkeypatch, tmp_path
) -> None:
    invoke, events = _new_aks_installation(
        monkeypatch, tmp_path, {"state": "blocked", "blockers": ["quota_cores_insufficient"]}
    )
    status = tmp_path / "work" / "run" / "status.json"
    status.parent.mkdir(parents=True, mode=0o700)
    (tmp_path / "work").chmod(0o700)
    status.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="stop-at-discovery"):
        invoke()

    assert events == ["stage:azure", "stage:kit", "stage:discovery"]
