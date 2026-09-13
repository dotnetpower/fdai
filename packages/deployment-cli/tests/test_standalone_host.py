from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_application, standalone_host
from fdai_deployment_cli.contracts import canonical_digest


def _review() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "substrate",
        "plan_digest": "a" * 64,
        "target_binding": "b" * 64,
        "source_commit": "c" * 40,
        "summary": {"action_counts": {"create": 1}},
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    value["review_digest"] = canonical_digest(value)
    return value


def _context(review: dict[str, object]) -> dict[str, object]:
    return {
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
    }


def test_standalone_plan_summary_counts_replacements_once() -> None:
    result = standalone_host._plan_summary(
        {
            "resource_changes": [
                {
                    "address": "azurerm_resource_group.main",
                    "type": "azurerm_resource_group",
                    "change": {"actions": ["create"]},
                },
                {
                    "address": "azurerm_linux_virtual_machine.runner",
                    "type": "azurerm_linux_virtual_machine",
                    "change": {"actions": ["delete", "create"]},
                },
                {
                    "address": "azurerm_container_app.core",
                    "type": "azurerm_container_app",
                    "change": {"actions": ["update"]},
                },
            ]
        }
    )

    assert result["action_counts"] == {
        "create": 1,
        "update": 1,
        "delete": 0,
        "replace": 1,
        "read": 0,
        "no-op": 0,
    }
    assert result["resource_type_counts"] == {
        "azurerm_container_app": 1,
        "azurerm_linux_virtual_machine": 1,
        "azurerm_resource_group": 1,
    }
    assert result["resource_changes"] == [
        {"address": "azurerm_resource_group.main", "actions": ["create"]},
        {
            "address": "azurerm_linux_virtual_machine.runner",
            "actions": ["delete", "create"],
        },
        {"address": "azurerm_container_app.core", "actions": ["update"]},
    ]


def test_standalone_apply_requires_exact_unexpired_approval() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }

    standalone_host._validate_approval(review, approval, context=_context(review))

    approval["plan_digest"] = "e" * 64
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))


def test_standalone_apply_rejects_expired_approval() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }

    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))


def test_standalone_checkpoint_lock_allows_only_one_writer(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    first = standalone_host._acquire_checkpoint_lock(tmp_path)
    try:
        with pytest.raises(ValueError, match="already running"):
            standalone_host._acquire_checkpoint_lock(tmp_path)
    finally:
        os.close(first)

    second = standalone_host._acquire_checkpoint_lock(tmp_path)
    os.close(second)


def test_standalone_apply_rejects_tampered_review_and_context() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }
    review["summary"] = {"action_counts": {"delete": 1}}
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))

    review = _review()
    approval["review_digest"] = review["review_digest"]
    approval["plan_digest"] = review["plan_digest"]
    approval["target_binding"] = review["target_binding"]
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(
            review,
            approval,
            context={**_context(review), "target_binding": "e" * 64},
        )


def test_remote_preparation_uses_only_fixed_argument_commands(tmp_path: Path) -> None:
    class Tunnel:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def ssh(self, command: tuple[str, ...], *, timeout: int):
            del timeout
            self.commands.append(command)
            stdout = "a" * 64 + "  kit.tar.gz\n" if command[0] == "sha256sum" else ""
            return SimpleNamespace(returncode=0, stdout=stdout)

        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del source, destination, timeout

    tunnel = Tunnel()
    inputs = []
    for name in ("archive", "handoff", "entra"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        inputs.append(path)
    standalone_application._prepare_remote(
        tunnel,
        remote_root="/home/fdai/.fdai-transfer-abc",
        remote_archive="/home/fdai/.fdai-transfer-abc/kit.tar.gz",
        archive=inputs[0],
        archive_digest="a" * 64,
        handoff_path=inputs[1],
        remote_handoff="/home/fdai/.fdai-transfer-abc/handoff.json",
        entra_path=inputs[2],
        remote_entra="/home/fdai/.fdai-transfer-abc/entra.json",
        app_work="/home/fdai/.fdai-transfer-abc/application",
        timeout_seconds=1800,
    )

    assert all(command[0] not in {"bash", "sh"} for command in tunnel.commands)
    assert any(command[:3] == ("python3", "-m", "venv") for command in tunnel.commands)
    assert tunnel.commands[-1][1:3] == ("-m", "fdai_deployment_cli.standalone_host")


def test_destructive_plan_requires_a_second_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    review = _review()
    review["stage"] = "application"
    review["summary"] = {"action_counts": {"create": 0, "update": 0, "delete": 1, "replace": 1}}
    review["review_digest"] = canonical_digest(
        {key: value for key, value in review.items() if key != "review_digest"}
    )
    answers = iter(("application-apply", "denied"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(standalone_application, "_azure_actor_digest", lambda _binding: "d" * 64)

    with pytest.raises(ValueError, match="destructive"):
        standalone_application._approve_plan(tmp_path, review)
    assert not (tmp_path / "application-approval.json").exists()


def test_ambiguous_apply_recovers_by_verification_without_reapply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim_path = tmp_path / "substrate-claim.json"
    claim_path.write_text("claim", encoding="utf-8")
    context = {
        "target_binding": "b" * 64,
        "infra": str(tmp_path),
    }
    review = {"plan_digest": "a" * 64}
    claim = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": "substrate",
        "plan_digest": review["plan_digest"],
        "idempotency_key": canonical_digest(
            {
                "target_binding": context["target_binding"],
                "plan_digest": review["plan_digest"],
            }
        ),
    }

    def private_json(path: Path, _label: str):
        if path.name == "context.json":
            return context
        if path.name == "substrate-review.json":
            return review
        return claim

    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    written: dict[str, object] = {}
    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host.subprocess, "run", run)
    monkeypatch.setattr(standalone_host, "_readback_stage", lambda *_: True)
    monkeypatch.setattr(
        standalone_host,
        "_replace_private_json",
        lambda _path, value: written.update(value),
    )

    result = standalone_host._recover_apply(SimpleNamespace(stage="substrate"), tmp_path)

    assert result["verification_only_recovery"] is True
    assert result["control_plane_readback_verified"] is True
    assert commands and commands[0][1] == "plan"
    assert all("apply" not in command for command in commands)
    assert written["state"] == "applied"


def test_standalone_migration_uses_interpreter_for_private_bundle_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    infra = bundle / "infra"
    infra.mkdir(parents=True)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "substrate-receipt.json").write_text("{}", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def private_json(path: Path, _label: str) -> dict[str, object]:
        if path.name == "context.json":
            return {"infra": str(infra), "source_commit": "c" * 40}
        service_id = "core-control-plane"
        if path.name.endswith("-schema.json"):
            return {
                "schema_version": 1,
                "service_id": service_id,
                "observed_schema_fingerprint": "fingerprint",
            }
        return {
            "service_id": service_id,
            "observed_schema_fingerprint": "fingerprint",
        }

    def run_env(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> None:
        commands.append(command)
        if "--evidence-output" in command:
            evidence = Path(command[command.index("--evidence-output") + 1])
            schema = Path(command[command.index("--schema-output") + 1])
            evidence.write_text("{}", encoding="utf-8")
            schema.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_terraform_output", lambda *_: "unused")
    monkeypatch.setattr(standalone_host, "_vault_name", lambda *_: "vault")
    monkeypatch.setattr(standalone_host, "_capture", lambda *_args, **_kwargs: "dsn")
    monkeypatch.setattr(
        standalone_host,
        "_capture_env",
        lambda *_args, **_kwargs: "core-control-plane\n",
    )
    monkeypatch.setattr(standalone_host, "_run_env", run_env)
    monkeypatch.setattr(standalone_host, "_replace_private_json", lambda *_: None)

    result = standalone_host._migrate(SimpleNamespace(), work_dir)

    migration_commands = [command for command in commands if "--evidence-output" in command]
    assert migration_commands == [
        (
            "/bin/sh",
            str(bundle / "service-migrations/bin/core-control-plane"),
            "bootstrap",
            "--evidence-output",
            str(work_dir / "migration-evidence/core-control-plane.json"),
            "--schema-output",
            str(work_dir / "migration-evidence/core-control-plane-schema.json"),
            "--rollback-reference",
            "bundle:cccccccccccccccccccccccccccccccccccccccc:service-migrations/branches/core-control-plane/adoption.json#rollback",
        )
    ]
    assert result["state"] == "migrated"


def test_private_service_migration_launcher_runs_through_fixed_interpreter(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[3]
    launcher = tmp_path / "service-migrations/bin/core-control-plane"
    launcher.parent.mkdir(parents=True)
    shutil.copyfile(repository / "service-migrations/bin/core-control-plane", launcher)
    launcher.chmod(0o600)
    fake_python = tmp_path / "migration-python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\"\n",
        encoding="ascii",
    )
    fake_python.chmod(0o700)

    result = subprocess.run(
        ["/bin/sh", str(launcher), "bootstrap"],
        env={**os.environ, "FDAI_MIGRATION_PYTHON": str(fake_python)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("service-migrations/migrate.py core-control-plane bootstrap\n")
