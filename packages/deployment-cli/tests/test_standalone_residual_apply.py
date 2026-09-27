from __future__ import annotations

import json
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli import standalone_host, standalone_residual_apply, standalone_review
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
