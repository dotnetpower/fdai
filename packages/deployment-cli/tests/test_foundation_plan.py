from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_foundation_input import BINDING, foundation_values, write_values

from fdai_deployment_cli import cli
from fdai_deployment_cli.contracts import ProvisionProfile


@pytest.fixture
def foundation_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[str], Path, ProvisionProfile]:
    profile = ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding=BINDING,
        connectivity="offline",
        host="managed-vm",
        transport="manual",
        access_method="internal_ssh",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=500,
    )
    monkeypatch.setattr(cli, "load_profile", lambda _: profile)
    monkeypatch.setattr(cli, "azure_active_target_binding", lambda: BINDING)
    monkeypatch.setattr(cli, "_read_public_key", lambda _: b"synthetic-public-key")
    monkeypatch.setattr(
        cli,
        "verify_offline_kit",
        lambda *a, **kw: SimpleNamespace(
            bundle_version="test",
            manifest_digest="a" * 64,
            file_digests=(("tools/terraform", "c" * 64),),
            terraform_binary="tools/terraform",
        ),
    )
    work = tmp_path / "work"
    bundle = tmp_path / "bundle"
    root = bundle / "infra" / "genesis-foundation"
    root.mkdir(parents=True)
    (root / ".terraform.lock.hcl").write_text("# synthetic lock", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "materialize_verified_artifacts",
        lambda *a, **kw: SimpleNamespace(
            terraform_binary=tmp_path / "terraform",
            provider_mirror=tmp_path / "mirror",
            deployment_bundle=tmp_path / "bundle.tar.gz",
        ),
    )
    monkeypatch.setattr(cli, "extract_bundle_archive", lambda *a, **kw: bundle)
    monkeypatch.setattr(
        cli,
        "verify_bundle",
        lambda *a, **kw: SimpleNamespace(
            bundle_version="test",
            manifest_digest="b" * 64,
        ),
    )
    monkeypatch.setattr(cli, "_terraform_environment", lambda **kw: {"TF_IN_AUTOMATION": "1"})
    monkeypatch.delenv("ARM_USE_MSI", raising=False)
    source = tmp_path / "input.json"
    write_values(source, foundation_values())
    args = [
        "provision",
        "plan",
        "--stage",
        "foundation",
        "--offline-kit",
        str(tmp_path / "kit"),
        "--release-root",
        str(tmp_path / "release.pub"),
        "--bundle-public-key",
        str(tmp_path / "bundle.pub"),
        "--profile",
        str(tmp_path / "profile.json"),
        "--work-dir",
        str(work),
        "--variables-file",
        str(source),
        "--output",
        "json",
    ]
    return args, root, profile


def test_foundation_cli_uses_only_selected_root_and_locked_providers(
    foundation_command: tuple[list[str], Path, ProvisionProfile],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, root, _ = foundation_command
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["cwd"] == root
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 300
        return subprocess.CompletedProcess(command, 0, "opaque-provider-marker", "")

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(args) == 0
    assert [call[1] for call in calls] == ["init", "plan"]
    assert "-backend=false" in calls[0]
    assert "-lockfile=readonly" in calls[0]
    assert not any(arg.startswith("-out=") for call in calls for arg in call)
    assert not (root.parents[2] / "work" / "plan.auto.tfvars.json").exists()
    captured = capsys.readouterr()
    assert "opaque-provider-marker" not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["state"] == "review"
    assert result["stage"] == "foundation"
    assert result["mutation_performed"] is False
    assert result["subscription_ready"] is False
    assert result["apply_authorized"] is False


@pytest.mark.parametrize("stage", ["init", "plan", "environment", "timeout"])
def test_failed_foundation_attempt_removes_snapshot_and_never_reports_success(
    foundation_command: tuple[list[str], Path, ProvisionProfile],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stage: str,
) -> None:
    args, root, _ = foundation_command
    calls: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command[1])
        if stage == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        return subprocess.CompletedProcess(
            command,
            1 if command[1] == stage else 0,
            "opaque-provider-marker",
            "",
        )

    def invalid_environment(**kwargs: object) -> dict[str, str]:
        raise ValueError("ambient Terraform control variables are not accepted")

    monkeypatch.setattr(cli.subprocess, "run", run)
    if stage == "environment":
        monkeypatch.setattr(cli, "_terraform_environment", invalid_environment)
    assert cli.main(args) == 3
    captured = capsys.readouterr()
    assert not captured.out
    assert "opaque-provider-marker" not in captured.err
    assert not (root.parents[2] / "work" / "plan.auto.tfvars.json").exists()
    if stage in {"init", "timeout"}:
        assert calls == ["init"]


@pytest.mark.parametrize(
    "condition",
    [
        "online",
        "existing-host",
        "zero-cost",
        "target",
        "unauthenticated",
        "msi",
        "missing-root",
    ],
)
def test_foundation_preconditions_block_terraform(
    foundation_command: tuple[list[str], Path, ProvisionProfile],
    monkeypatch: pytest.MonkeyPatch,
    condition: str,
) -> None:
    args, root, profile = foundation_command
    if condition == "online":
        profile = replace(profile, connectivity="online")
    elif condition == "existing-host":
        profile = replace(profile, host="existing-host")
    elif condition == "zero-cost":
        profile = replace(profile, monthly_cost_ceiling=0)
    elif condition == "target":
        monkeypatch.setattr(cli, "azure_active_target_binding", lambda: "c" * 64)
    elif condition == "unauthenticated":
        monkeypatch.setattr(cli, "azure_active_target_binding", lambda: None)
    elif condition == "msi":
        monkeypatch.setenv("ARM_USE_MSI", "true")
    elif condition == "missing-root":
        (root / ".terraform.lock.hcl").unlink()
    monkeypatch.setattr(cli, "load_profile", lambda _: profile)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Terraform must not run before foundation preconditions pass")

    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    assert cli.main(args) == 3


def test_platform_remains_default_stage() -> None:
    args = cli._parser().parse_args(
        [
            "provision",
            "plan",
            "--offline-kit",
            "kit",
            "--release-root",
            "release.pub",
            "--bundle-public-key",
            "bundle.pub",
            "--profile",
            "profile.json",
            "--variables-file",
            "input.json",
            "--work-dir",
            "work",
        ]
    )
    assert args.stage == "platform"


def test_platform_default_preserves_root_input_and_result(
    foundation_command: tuple[list[str], Path, ProvisionProfile],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, foundation_root, _ = foundation_command
    selection = args.index("--stage")
    del args[selection : selection + 2]
    values = foundation_values()
    write_values(
        Path(args[args.index("--variables-file") + 1]),
        {
            "tenant_id": values["tenant_id"],
            "subscription_id": values["subscription_id"],
            "target_binding": BINDING,
            "region": "koreacentral",
            "postgres_admin_login": "fdaiadmin",
            "postgres_admin_password": "FDAI-PLAN-ONLY-NOT-A-SECRET",
            "core_image": "ghcr.io/example/fdai:plan-only",
        },
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["cwd"] == foundation_root.parent
        if command[1] == "plan":
            snapshot = Path(
                next(
                    arg.removeprefix("-var-file=")
                    for arg in command
                    if arg.startswith("-var-file=")
                )
            )
            assert json.loads(snapshot.read_bytes())["env"] == "dev"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": "fdai.provision-plan.v1",
        "offline_manifest_digest": "a" * 64,
        "mutation_performed": False,
    }
