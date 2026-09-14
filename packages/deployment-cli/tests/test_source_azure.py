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


@pytest.mark.parametrize("mutation_performed", [False, True])
def test_source_plan_runs_preparation_before_review(tmp_path, monkeypatch, mutation_performed):
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
        source_azure, "prepare_source_deployment", lambda **_: {"source_commit": source.commit}
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
            write_private_bytes(
                foundation / "foundation-variables.json",
                b'{"subscription_id":"example","tenant_id":"example"}',
            )
            return {"state": "prepared"}
        assert Path(command[1]).name == "genesis_runner_image.py"
        assert command[2] == "plan"
        return {
            "schema_version": "fdai.genesis-runner-image-plan-result.v1",
            "state": "review",
            "apply_authorized": False,
            "mutation_performed": mutation_performed,
        }

    monkeypatch.setattr(source_azure, "_capture", capture)
    arguments = dict(
        source_root=root,
        work_dir=work_dir,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
        timeout_seconds=1800,
    )
    if mutation_performed:
        with pytest.raises(ValueError, match="review-only"):
            source_azure.plan_source_installation(**arguments)
        assert not (work_dir / "foundation/source-plan-review.json").exists()
    else:
        result = source_azure.plan_source_installation(**arguments)
        assert result["state"] == "review"
        assert result["deployment_ready"] is False
        assert result["release_signature_verified"] is False
        assert result["provenance"] == "operator-selected-source"
    assert len(calls) == 2


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


def test_source_plan_pending_approval_is_not_cli_success(monkeypatch, capsys) -> None:
    calls = []
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
                "json",
            ]
        )
        == 2
    )
    assert calls[0]["source_root"] == Path(".")
    assert '"deployment_ready":false' in capsys.readouterr().out
