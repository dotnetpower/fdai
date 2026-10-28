from __future__ import annotations

import json
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli import (
    standalone_host,
    standalone_host_residual,
    standalone_residual_apply,
    standalone_residual_successor,
    standalone_review,
)
from fdai_deployment_cli.contracts import canonical_digest


def _context() -> dict[str, object]:
    return {
        "target_binding": "a" * 64,
        "source_commit": "b" * 40,
        "runtime_profile_digest": "c" * 64,
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
        },
    }


def _original(context: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    review: dict[str, object] = {
        "plan_digest": "d" * 64,
    }
    claim: dict[str, object] = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": "substrate",
        "plan_digest": review["plan_digest"],
        "idempotency_key": canonical_digest(
            {
                "target_binding": context["target_binding"],
                "plan_digest": review["plan_digest"],
            }
        ),
        "mutation_performed": False,
    }
    return review, claim


def _prepare_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    context = _context()
    original_review, original_claim = _original(context)
    for name, value in (
        ("substrate-review.json", original_review),
        ("substrate-claim.json", original_claim),
    ):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)

    def run(command: tuple[str, ...] | list[str], **kwargs: object):
        if command[1] == "plan":
            output = next(value for value in command if value.startswith("-out="))
            plan = Path(output.removeprefix("-out="))
            plan.write_bytes(b"residual-plan")
            plan.chmod(0o644)
            return subprocess.CompletedProcess(command, 2, stdout=b"", stderr=b"")
        assert command[1:3] == ("show", "-json")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "resource_changes": [
                        {
                            "address": "azurerm_role_assignment.remaining",
                            "type": "azurerm_role_assignment",
                            "change": {"actions": ["create"]},
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", run)
    review = standalone_residual_apply.prepare_residual_review(
        work_dir=tmp_path,
        stage="substrate",
        context=context,
        infra=tmp_path,
        variables=tmp_path / "application.auto.tfvars.json",
        targets=("module.example",),
        original_review=original_review,
        original_claim=original_claim,
    )
    assert review is not None
    return context, original_review, original_claim


def test_partial_apply_creates_distinct_private_residual_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    context, original_review, original_claim = _prepare_review(tmp_path, monkeypatch)
    review = json.loads((tmp_path / "substrate-residual-review.json").read_text())

    assert review["residual_recovery"] == {
        "operation": "substrate-residual",
        "original_plan_digest": original_review["plan_digest"],
        "original_claim_digest": canonical_digest(original_claim),
    }
    assert review["target_binding"] == context["target_binding"]
    assert stat.S_IMODE((tmp_path / "substrate-residual.tfplan").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "substrate-residual-review.json").stat().st_mode) == 0o600


def test_residual_apply_claims_before_effect_and_requires_zero_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    context, original_review, original_claim = _prepare_review(tmp_path, monkeypatch)
    residual_review = json.loads((tmp_path / "substrate-residual-review.json").read_text())
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...] | list[str], **_kwargs: object):
        normalized = tuple(command)
        commands.append(normalized)
        if normalized[1] == "apply":
            assert (tmp_path / "substrate-residual-claim.json").is_file()
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", run)
    receipt = standalone_residual_apply.apply_residual_plan(
        work_dir=tmp_path,
        stage="substrate",
        context=context,
        infra=tmp_path,
        variables=tmp_path / "application.auto.tfvars.json",
        targets=("module.example",),
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        approval={"approved": True},
        effect_readback=lambda: True,
    )

    assert [command[1] for command in commands] == ["apply", "plan"]
    assert receipt["state"] == "applied"
    assert receipt["residual_recovery"] is True
    assert receipt["terraform_zero_change_verified"] is True
    assert receipt["verification_only_recovery"] is False
    assert (tmp_path / "substrate-claim.json").is_file()


def test_claimed_residual_effect_recovers_without_another_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    context, original_review, original_claim = _prepare_review(tmp_path, monkeypatch)
    residual_review = json.loads((tmp_path / "substrate-residual-review.json").read_text())

    def fail_apply(command: tuple[str, ...] | list[str], **_kwargs: object):
        return subprocess.CompletedProcess(
            command,
            1 if command[1] == "apply" else 0,
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", fail_apply)
    with pytest.raises(ValueError, match="verification-only"):
        standalone_residual_apply.apply_residual_plan(
            work_dir=tmp_path,
            stage="substrate",
            context=context,
            infra=tmp_path,
            variables=tmp_path / "application.auto.tfvars.json",
            targets=("module.example",),
            original_review=original_review,
            original_claim=original_claim,
            residual_review=residual_review,
            approval={"approved": True},
            effect_readback=lambda: True,
        )

    after_expiry = datetime.now(UTC) + timedelta(hours=2)

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return after_expiry

    monkeypatch.setattr(standalone_review, "datetime", ExpiredClock)
    commands: list[tuple[str, ...]] = []

    def recover(command: tuple[str, ...] | list[str], **_kwargs: object):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", recover)
    receipt = standalone_residual_apply.recover_residual_apply(
        work_dir=tmp_path,
        stage="substrate",
        context=context,
        infra=tmp_path,
        variables=tmp_path / "application.auto.tfvars.json",
        targets=("module.example",),
        original_review=original_review,
        original_claim=original_claim,
        effect_readback=lambda: True,
    )

    assert [command[1] for command in commands] == ["plan"]
    assert receipt["verification_only_recovery"] is True
    assert receipt["terraform_zero_change_verified"] is True


def test_failed_residual_creates_and_applies_one_create_only_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    context, original_review, original_claim = _prepare_review(tmp_path, monkeypatch)
    residual_review = json.loads((tmp_path / "substrate-residual-review.json").read_text())
    monkeypatch.setattr(
        standalone_residual_apply.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 1 if command[1] == "apply" else 0, stdout=b"", stderr=b""
        ),
    )
    with pytest.raises(ValueError, match="verification-only"):
        standalone_residual_apply.apply_residual_plan(
            work_dir=tmp_path,
            stage="substrate",
            context=context,
            infra=tmp_path,
            variables=tmp_path / "application.auto.tfvars.json",
            targets=("module.example",),
            original_review=original_review,
            original_claim=original_claim,
            residual_review=residual_review,
            approval={"approved": True},
            effect_readback=lambda: False,
        )

    def successor_plan(command, **_kwargs):
        if command[1] == "plan":
            output = next((value for value in command if value.startswith("-out=")), None)
            if output is not None:
                plan = Path(output.removeprefix("-out="))
                plan.write_bytes(b"successor-plan")
                plan.chmod(0o600)
            return subprocess.CompletedProcess(command, 2, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "resource_changes": [
                        {
                            "address": "azurerm_role_assignment.remaining",
                            "type": "azurerm_role_assignment",
                            "change": {"actions": ["create"]},
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", successor_plan)
    monkeypatch.setattr(standalone_residual_successor.subprocess, "run", successor_plan)
    successor = standalone_residual_apply.recover_residual_apply(
        work_dir=tmp_path,
        stage="substrate",
        context=context,
        infra=tmp_path,
        variables=tmp_path / "application.auto.tfvars.json",
        targets=("module.example",),
        original_review=original_review,
        original_claim=original_claim,
        effect_readback=lambda: False,
        successor_prerequisite_verified=True,
    )
    assert successor["residual_successor"]["operation"] == "substrate-residual-successor"

    commands: list[tuple[str, ...]] = []

    def apply_successor(command, **_kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", apply_successor)
    receipt = standalone_residual_successor.apply_residual_successor(
        work_dir=tmp_path,
        stage="substrate",
        context=context,
        infra=tmp_path,
        variables=tmp_path / "application.auto.tfvars.json",
        targets=("module.example",),
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=json.loads((tmp_path / "substrate-residual-claim.json").read_text()),
        successor_review=successor,
        approval={"approved": True},
        effect_readback=lambda: True,
    )
    assert [command[1] for command in commands] == ["apply", "plan"]
    assert receipt["residual_successor"] is True
    assert receipt["terraform_zero_change_verified"] is True


def test_residual_successor_rejects_non_create_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    context, original_review, original_claim = _prepare_review(tmp_path, monkeypatch)
    residual_review = json.loads((tmp_path / "substrate-residual-review.json").read_text())
    residual_claim = standalone_residual_apply._residual_claim(
        stage="substrate",
        context=context,
        original_claim=original_claim,
        residual_review=residual_review,
        approval={"approved": True},
    )
    residual_claim_path = tmp_path / "substrate-residual-claim.json"
    residual_claim_path.write_text(json.dumps(residual_claim))
    residual_claim_path.chmod(0o600)

    def changed_plan(command, **_kwargs):
        if command[1] == "plan":
            output = next((value for value in command if value.startswith("-out=")), None)
            if output is not None:
                plan = Path(output.removeprefix("-out="))
                plan.write_bytes(b"successor-plan")
                plan.chmod(0o600)
            return subprocess.CompletedProcess(command, 2, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "resource_changes": [
                        {
                            "address": "azurerm_resource.changed",
                            "type": "azurerm_resource",
                            "change": {"actions": ["update"]},
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(standalone_residual_apply.subprocess, "run", changed_plan)
    monkeypatch.setattr(standalone_residual_successor.subprocess, "run", changed_plan)
    with pytest.raises(ValueError, match="creates and at most one"):
        standalone_residual_apply.recover_residual_apply(
            work_dir=tmp_path,
            stage="substrate",
            context=context,
            infra=tmp_path,
            variables=tmp_path / "application.auto.tfvars.json",
            targets=("module.example",),
            original_review=original_review,
            original_claim=original_claim,
            effect_readback=lambda: False,
            successor_prerequisite_verified=True,
        )


def test_application_successor_allows_one_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context()
    original_review, original_claim = _original(context)
    original_claim["stage"] = "application"
    residual_review = {
        "plan_digest": "e" * 64,
    }
    residual_claim = {"claim": "residual"}
    monkeypatch.setattr(
        standalone_residual_successor,
        "_validate_residual_claim",
        lambda **_kwargs: None,
    )

    def plan(command, **_kwargs):
        if command[1] == "plan":
            output = next(value for value in command if value.startswith("-out="))
            path = Path(output.removeprefix("-out="))
            path.write_bytes(b"successor")
            path.chmod(0o600)
            return subprocess.CompletedProcess(command, 2, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "resource_changes": [
                        {
                            "address": "kubernetes_deployment_v1.workload",
                            "type": "kubernetes_deployment_v1",
                            "change": {"actions": ["delete", "create"]},
                        },
                        {
                            "address": "azurerm_network_security_rule.gateway",
                            "type": "azurerm_network_security_rule",
                            "change": {"actions": ["create"]},
                        },
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(standalone_residual_successor.subprocess, "run", plan)
    review = standalone_residual_successor.prepare_residual_successor_review(
        work_dir=tmp_path,
        stage="application",
        context=context,
        infra=tmp_path,
        variables=tmp_path / "workloads.auto.tfvars.json",
        targets=("module.example",),
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
        successor_prerequisite_verified=True,
    )

    assert review["summary"]["action_counts"]["replace"] == 1


def test_residual_apply_command_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(
        standalone_host,
        "_apply_residual",
        lambda _args, _work_dir: {
            "schema_version": "fdai.standalone-residual-apply-receipt.v1",
            "state": "applied",
        },
    )

    result = standalone_host.main(
        [
            "--work-dir",
            str(tmp_path),
            "apply-residual",
            "--stage",
            "substrate",
            "--approval",
            str(tmp_path / "approval.json"),
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["state"] == "applied"


def _residual_checkpoint_loaded_files(work_dir: Path) -> list[str]:
    loaded: list[str] = []

    def private_json(path: Path, _label: str) -> dict[str, object]:
        loaded.append(path.name)
        return {}

    class _Stop(Exception):
        pass

    def stop(*_args, **_kwargs):
        raise _Stop

    args = type("Args", (), {"stage": "runtime", "approval": work_dir / "approval.json"})()
    with pytest.raises(_Stop):
        standalone_host_residual.apply_residual_checkpoint(
            args,
            work_dir,
            private_json=private_json,
            validate_approval=stop,
            managed_identity_login=stop,
            stage_paths=stop,
            activate_stage=stop,
            stage_targets=stop,
            guard_runtime=stop,
            readback_stage=stop,
            absolute_path=lambda path: path,
        )
    return loaded


def test_runtime_residual_extends_the_unreceipted_runtime_cluster_claim(tmp_path: Path) -> None:
    (tmp_path / "runtime-cluster-claim.json").write_text("{}")

    loaded = _residual_checkpoint_loaded_files(tmp_path)

    assert "runtime-cluster-review.json" in loaded
    assert "runtime-cluster-claim.json" in loaded
    assert "runtime-review.json" not in loaded


def test_runtime_residual_uses_the_runtime_claim_after_the_cluster_receipt(tmp_path: Path) -> None:
    (tmp_path / "runtime-cluster-claim.json").write_text("{}")
    (tmp_path / "runtime-cluster-receipt.json").write_text("{}")

    loaded = _residual_checkpoint_loaded_files(tmp_path)

    assert "runtime-review.json" in loaded
    assert "runtime-cluster-review.json" not in loaded
