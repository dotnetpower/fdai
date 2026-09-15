"""Source orchestration stops on feasibility failure before any provider mutation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import cli, source_azure
from fdai_deployment_cli.private_output import write_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


@pytest.mark.parametrize("deployment_ready", [False, True])
@pytest.mark.parametrize("mode", ["review", "interactive", "approved", "ambient", "startup"])
def test_source_plan_runs_preparation_before_review(tmp_path, monkeypatch, deployment_ready, mode):
    interactive = mode == "interactive"
    approval_file = tmp_path / "approved-checkpoint.json" if mode == "approved" else None
    if approval_file is not None:
        write_private_bytes(approval_file, b"example exact approval")
    root = tmp_path / "checkout"
    toolchain = root / "infra/genesis-runner-image/toolchain.json"
    toolchain.parent.mkdir(parents=True)
    executable = tmp_path / "terraform"
    executable.write_bytes(b"example executable")
    executable.chmod(0o700)
    toolchain.write_text(
        json.dumps(
            {
                "terraform_binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
        )
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir(mode=0o700)
    source = SimpleNamespace(root=root, commit="c" * 40, reverify=lambda: None)
    monkeypatch.setattr(source_azure, "inspect_source", lambda *_, **__: source)
    monkeypatch.setattr(
        source_azure,
        "prepare_source_deployment",
        lambda **_: {
            "source_commit": source.commit,
            "source_snapshot_digest": "e" * 64,
            "receipt_digest": "d" * 64,
        },
    )
    monkeypatch.setattr(
        source_azure,
        "inspect_aks_target",
        lambda **_: {"state": "feasible", "target_binding": "a" * 64},
    )
    monkeypatch.setattr(source_azure.shutil, "which", lambda _: str(executable))
    calls = []

    def capture(command, cwd, environment, timeout):
        calls.append(command)
        assert cwd == root
        assert "FDAI_SIGNED_SOURCE_EVIDENCE" not in environment
        assert 0 < timeout <= 1800
        if len(calls) == 1:
            assert Path(command[1]).name == "source_genesis.py"
            foundation = work_dir / "foundation"
            foundation.mkdir(mode=0o700)
            if mode == "ambient":
                write_private_bytes(
                    foundation / "current-source-approval.json", b"unselected approval"
                )
            write_private_bytes(
                foundation / "foundation-variables.json",
                b'{"subscription_id":"example","tenant_id":"example"}',
            )
            return {"state": "prepared", "run_binding": "f" * 64}
        assert Path(command[1]).name == "source_genesis.py"
        assert "--advance" in command
        assert ("--approval-file" in command) == (approval_file is not None or len(calls) > 2)
        if approval_file is not None:
            assert command[command.index("--approval-file") + 1] == str(approval_file)
        stage = (
            "runner-image-apply"
            if len(calls) == 2 and approval_file is None
            else "application-plan"
        )
        status_path = work_dir / "foundation/status.json"
        status_path.write_text(
            json.dumps(
                {
                    "schema_version": "fdai.genesis-orchestration-status.v2",
                    "attempt": len(calls) - 1,
                    "sequence": 1,
                    "source_commit": source.commit,
                    "target_binding": "f" * 64,
                    "mode": "apply",
                    "state": "waiting",
                    "current_stage": stage,
                    "mutation_performed": False,
                }
            )
        )
        status_path.chmod(0o600)
        return {
            "schema_version": "fdai.source-foundation-progress.v1",
            "state": "review",
            "apply_authorized": False,
            "mutation_performed": False,
            "deployment_ready": deployment_ready,
            "source_commit": source.commit,
            "run_binding": "f" * 64,
            "provenance": "operator-selected-source",
            "release_signature_verified": False,
            "stage": stage,
            "attempt": len(calls) - 1,
        }

    monkeypatch.setattr(source_azure, "_capture", capture)
    prompts = []

    def prompt(command, **kwargs):
        assert interactive
        assert Path(command[1]).name == "genesis_approval_prompt.py"
        prompts.append(command)
        write_private_bytes(Path(command[-1]), b"example exact approval")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(source_azure.subprocess, "run", prompt)
    initial_confirmations = []
    if mode == "startup":
        from fdai_deployment_cli import installation_scope

        monkeypatch.setattr(
            installation_scope,
            "_read_initial_answer",
            lambda deadline: initial_confirmations.append(deadline) or "install",
        )
    arguments = dict(
        source_root=root,
        work_dir=work_dir,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
        timeout_seconds=1800,
        interactive=interactive,
        approval_file=approval_file,
        installation_options=(
            installation_scope.InstallationOptions(setup_cost_ceiling=300)
            if mode == "startup"
            else None
        ),
        confirm_initial=mode == "startup",
    )
    if deployment_ready:
        with pytest.raises(ValueError, match="bound review"):
            source_azure.plan_source_installation(**arguments)
        assert not (work_dir / "foundation/source-plan-review.json").exists()
    else:
        result = source_azure.plan_source_installation(**arguments)
        assert result["state"] == "review"
        assert result["deployment_ready"] is False
        assert result["release_signature_verified"] is False
        assert result["provenance"] == "operator-selected-source"
    assert len(calls) == (3 if interactive and not deployment_ready else 2)
    assert len(prompts) == int(interactive and not deployment_ready)
    assert len(initial_confirmations) == int(mode == "startup")
    if approval_file is not None:
        assert approval_file.read_bytes() == b"example exact approval"


def test_source_orchestration_stops_before_foundation_on_capacity_block(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        source_azure, "prepare_source_deployment", lambda **_: {"source_commit": "c" * 40}
    )
    monkeypatch.setattr(
        source_azure,
        "inspect_source",
        lambda *_, **__: SimpleNamespace(commit="c" * 40, root=tmp_path),
    )
    monkeypatch.setattr(
        source_azure,
        "inspect_aks_target",
        lambda **_: {
            "state": "blocked",
            "blockers": ["system_sku_restricted_or_unknown"],
            "deployment_ready": False,
        },
    )
    result = source_azure.plan_source_installation(
        source_root=tmp_path,
        work_dir=tmp_path / "work",
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
        timeout_seconds=1800,
    )
    assert result["stage"] == "aks-preflight"
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("output", ["text", "json"])
@pytest.mark.parametrize("approved", [False, True])
def test_source_plan_pending_approval_is_not_cli_success(
    monkeypatch, capsys, output, approved
) -> None:
    calls = []
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        cli,
        "plan_source_installation",
        lambda **kwargs: calls.append(kwargs) or {"state": "review", "deployment_ready": False},
    )
    assert (
        cli.main(
            [
                "provision",
                "azure",
                "--source",
                ".",
                "--runtime",
                "aks",
                "--work-dir",
                "/tmp/example-source-run",
                "--output",
                output,
                *(["--approval-file", "/tmp/example-approval.json"] if approved else []),
            ]
        )
        == 2
    )
    assert calls[0]["source_root"] == Path(".")
    assert calls[0]["interactive"] is False
    assert calls[0]["confirm_initial"] is (output == "text")
    assert (calls[0]["installation_options"] is None) is approved
    assert calls[0]["approval_file"] == (Path("/tmp/example-approval.json") if approved else None)
    text = capsys.readouterr().out
    assert ('"deployment_ready":false' in text) if output == "json" else ("not ready" in text)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--online"],
        ["--source", ".", "--prepare-only"],
        ["--source", ".", "--preflight-only"],
    ],
)
def test_source_approval_cannot_be_silently_ignored(monkeypatch, capsys, arguments) -> None:
    monkeypatch.setattr(cli, "plan_source_installation", lambda **_: pytest.fail("no execution"))
    assert (
        cli.main(
            ["provision", "azure", *arguments, "--approval-file", "/tmp/example-approval.json"]
        )
        == 3
    )
    assert "--approval-file requires source deployment" in capsys.readouterr().err


@pytest.mark.parametrize("confirmation_state", ["review", "confirmed"])
def test_initial_confirmation_precedes_foundation_and_does_not_enable_interactive(
    tmp_path, monkeypatch, confirmation_state
):
    from fdai_deployment_cli.installation_scope import InstallationOptions

    source = SimpleNamespace(commit="c" * 40, root=tmp_path, reverify=lambda: None)
    monkeypatch.setattr(
        source_azure,
        "prepare_source_deployment",
        lambda **_: {
            "source_commit": source.commit,
            "receipt_digest": "d" * 64,
        },
    )
    monkeypatch.setattr(source_azure, "inspect_source", lambda *_, **__: source)
    monkeypatch.setattr(
        source_azure,
        "inspect_aks_target",
        lambda **_: {
            "state": "feasible",
            "target_binding": "a" * 64,
        },
    )
    calls = []
    monkeypatch.setattr(
        source_azure,
        "confirm_installation_scope",
        lambda **kwargs: (
            calls.append(kwargs) or {"state": confirmation_state, "deployment_ready": False}
        ),
    )

    def capture(*_args):
        assert confirmation_state == "confirmed"
        assert len(calls) == 1
        raise RuntimeError("reached-foundation-after-confirmation")

    monkeypatch.setattr(source_azure, "_capture", capture)
    arguments = dict(
        source_root=tmp_path,
        work_dir=tmp_path / "work",
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1200,
        timeout_seconds=1800,
        installation_options=InstallationOptions(setup_cost_ceiling=300),
        confirm_initial=True,
    )
    if confirmation_state == "confirmed":
        arguments["work_dir"].mkdir()
        toolchain = tmp_path / "infra/genesis-runner-image/toolchain.json"
        toolchain.parent.mkdir(parents=True)
        executable = tmp_path / "terraform"
        executable.write_bytes(b"example executable")
        executable.chmod(0o700)
        toolchain.write_text(
            json.dumps(
                {"terraform_binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
            )
        )
        monkeypatch.setattr(source_azure.shutil, "which", lambda _: str(executable))
        with pytest.raises(RuntimeError, match="reached-foundation-after-confirmation"):
            source_azure.plan_source_installation(**arguments)
        assert (arguments["work_dir"] / "source-tools").is_dir()
    else:
        assert source_azure.plan_source_installation(**arguments)["state"] == "review"
        assert not arguments["work_dir"].exists()
    assert calls[0]["binding"]["preparation_digest"] == "d" * 64
    assert calls[0]["options"].setup_cost_ceiling == 300


@pytest.mark.parametrize(
    "arguments",
    [
        ["--online"],
        ["--source", ".", "--prepare-only"],
        ["--source", ".", "--preflight-only"],
        ["--source", ".", "--approval-file", "/tmp/approval.json"],
    ],
)
def test_initial_scope_options_cannot_be_ignored(monkeypatch, capsys, arguments):
    monkeypatch.setattr(cli, "plan_source_installation", lambda **_: pytest.fail("no execution"))
    assert cli.main(["provision", "azure", *arguments, "--setup-cost-ceiling", "300"]) == 3
    assert "initial scope options require" in capsys.readouterr().err
