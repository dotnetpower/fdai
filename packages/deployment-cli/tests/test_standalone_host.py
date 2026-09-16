from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_application, standalone_host
from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.contracts import canonical_digest


@pytest.mark.parametrize("artifact_directory", ["kit-work/verified", "source-work/verified"])
def test_runtime_support_uses_only_admitted_artifact_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact_directory: str
) -> None:
    artifact_root = tmp_path / artifact_directory
    wheels = artifact_root / "support/python"
    wheels.mkdir(parents=True)
    wheel = wheels / "example-1.0-py3-none-any.whl"
    wheel.write_bytes(b"synthetic-wheel")
    decoy = tmp_path / "other-artifacts/support/python"
    decoy.mkdir(parents=True)
    (decoy / "unexpected.whl").write_bytes(b"not-selected")
    calls: list[tuple[str, ...]] = []

    def capture(command, **kwargs):
        assert kwargs["cwd"] == tmp_path
        calls.append(command)

    monkeypatch.setattr(standalone_host, "_run", capture)
    standalone_host._install_runtime_support(tmp_path, artifact_root=artifact_root)

    assert len(calls) == 2
    assert calls[1] == (
        str(tmp_path / "runtime-venv/bin/pip"),
        "install",
        "--no-index",
        "--no-cache-dir",
        str(wheel),
    )


def test_runtime_support_does_not_fall_back_to_kit(tmp_path: Path, monkeypatch) -> None:
    decoy = tmp_path / "kit-work/verified/support/python"
    decoy.mkdir(parents=True)
    (decoy / "unexpected.whl").write_bytes(b"not-selected")

    def unexpected(*args, **kwargs):
        pytest.fail("missing admitted support must not execute an installer")

    monkeypatch.setattr(standalone_host, "_run", unexpected)
    with pytest.raises(ValueError, match="wheelhouse is empty"):
        standalone_host._install_runtime_support(
            tmp_path, artifact_root=tmp_path / "source-work/verified"
        )


def test_foundation_application_workload_matches_resource_group_name() -> None:
    assert (
        standalone_host._foundation_application_workload(
            {"name": "rg-fdaiaks-dev-wus2"},
            environment="dev",
            region_short="wus2",
        )
        == "fdaiaks"
    )


@pytest.mark.parametrize(
    "name",
    [
        "rg-fdaiaks-staging-wus2",
        "rg-fdaiaks-dev-krc",
        "rg-invalid/name-dev-wus2",
    ],
)
def test_foundation_application_workload_rejects_mismatched_name(name: str) -> None:
    with pytest.raises(ValueError, match="Foundation application"):
        standalone_host._foundation_application_workload(
            {"name": name},
            environment="dev",
            region_short="wus2",
        )


def test_aks_baseline_defers_detailed_private_networking() -> None:
    source = Path(standalone_host.__file__).read_text(encoding="utf-8")

    assert '"enable_private_networking": not aks_baseline' in source
    assert '"acr_sku": "Basic" if aks_baseline else "Premium"' in source


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


def test_remote_preparation_transfers_exact_adoption_inputs(tmp_path: Path) -> None:
    class Tunnel:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []
            self.copies: list[tuple[Path, str]] = []

        def ssh(self, command: tuple[str, ...], *, timeout: int):
            del timeout
            self.commands.append(command)
            stdout = "a" * 64 + "  kit.tar.gz\n" if command[0] == "sha256sum" else ""
            return SimpleNamespace(returncode=0, stdout=stdout)

        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del timeout
            self.copies.append((source, destination))

    paths = [
        tmp_path / name for name in ("archive", "handoff", "entra", "state", "models", "adoption")
    ]
    for path in paths:
        path.write_text(path.name, encoding="utf-8")
    adoption = ApplicationStateAdoption(
        state=paths[3],
        resolved_models=paths[4],
        descriptor=paths[5],
        resource_name_suffix="abcdef",
        managed_resource_count=3,
    )
    tunnel = Tunnel()

    standalone_application._prepare_remote(
        tunnel,
        remote_root="/home/fdai/.fdai-transfer-abc",
        remote_archive="/home/fdai/.fdai-transfer-abc/kit.tar.gz",
        archive=paths[0],
        archive_digest="a" * 64,
        handoff_path=paths[1],
        remote_handoff="/home/fdai/.fdai-transfer-abc/handoff.json",
        entra_path=paths[2],
        remote_entra="/home/fdai/.fdai-transfer-abc/entra.json",
        app_work="/home/fdai/.fdai-transfer-abc/application",
        application_state_adoption=adoption,
        remote_adoption_state="/home/fdai/.fdai-transfer-abc/application-state.json",
        remote_adoption_models="/home/fdai/.fdai-transfer-abc/resolved-models.json",
        remote_adoption_descriptor="/home/fdai/.fdai-transfer-abc/adoption.json",
        timeout_seconds=1800,
    )

    assert tunnel.copies[-3:] == [
        (paths[3], "/home/fdai/.fdai-transfer-abc/application-state.json"),
        (paths[4], "/home/fdai/.fdai-transfer-abc/resolved-models.json"),
        (paths[5], "/home/fdai/.fdai-transfer-abc/adoption.json"),
    ]
    prepare = tunnel.commands[-1]
    assert prepare[prepare.index("--adoption-state") + 1].endswith("application-state.json")
    assert prepare[prepare.index("--adoption-models") + 1].endswith("resolved-models.json")
    assert prepare[prepare.index("--adoption-descriptor") + 1].endswith("adoption.json")


def _adoption_inputs(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path]:
    tmp_path.chmod(0o700)
    state = tmp_path / "application-state.json"
    models = tmp_path / "resolved-models.json"
    descriptor_path = tmp_path / "adoption.json"
    payload = {
        "version": 4,
        "serial": 2,
        "lineage": "lineage",
        "resources": [
            {
                "mode": "managed",
                "type": "terraform_data",
                "name": "example",
                "instances": [{"attributes": {"id": "opaque"}}],
            }
        ],
    }
    state.write_text(json.dumps(payload), encoding="utf-8")
    models.write_text("{}", encoding="utf-8")
    descriptor_path.write_text("{}", encoding="utf-8")
    for path in (state, models, descriptor_path):
        path.chmod(0o600)
    descriptor: dict[str, object] = {
        "staged_state_sha256": standalone_host._file_digest(state),
        "managed_resource_count": 1,
    }
    return descriptor, state, models, descriptor_path


@pytest.mark.parametrize("change", ["count", "owner"])
def test_staged_application_state_is_rejected_before_push(tmp_path: Path, change: str) -> None:
    descriptor, state, _models, _descriptor_path = _adoption_inputs(tmp_path)
    if change == "count":
        descriptor["managed_resource_count"] = 2
    else:
        payload = json.loads(state.read_text(encoding="utf-8"))
        payload["resources"].append(
            {
                "module": "module.resource_group",
                "mode": "managed",
                "type": "terraform_data",
                "name": "ownership",
                "instances": [{"attributes": {"input": "managed"}}],
            }
        )
        state.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="count differs|retains a resource-group owner"):
        standalone_host._validate_staged_application_state(state, descriptor)


def test_deployment_binding_uses_terraform_core_app_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "substrate-receipt.json").write_text("{}", encoding="utf-8")
    context = {
        "infra": str(tmp_path / "infra"),
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    context_path.chmod(0o600)
    observed: list[tuple[Path, str]] = []

    def terraform_output(infra: Path, name: str) -> str:
        observed.append((infra, name))
        return "ca-fdai-dev-wus2-core"

    monkeypatch.setattr(standalone_host, "_terraform_output", terraform_output)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    result = standalone_host._deployment_binding(SimpleNamespace(), tmp_path)

    expected = hashlib.sha256(
        (f"{context['tenant_id']}\0{context['subscription_id']}\0ca-fdai-dev-wus2-core").encode()
    ).hexdigest()
    assert result["deployment_binding"] == expected
    assert result["terraform_name_verified"] is True
    assert observed == [(tmp_path / "infra", "core_app_name")]


def test_application_state_adoption_pushes_once_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    expected = state.read_text(encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        calls.append(command)
        if command[:4] == ("az", "storage", "blob", "exists"):
            return "false\n"
        payload = json.loads(expected)
        payload["serial"] += 1
        return json.dumps(payload)

    monkeypatch.setattr(standalone_host, "_capture", capture)
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda command, **_kwargs: calls.append(tuple(command)),
    )
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }

    standalone_host._adopt_application_state(
        tmp_path, context, descriptor, state, models, descriptor_path
    )

    assert sum(command[:3] == ("terraform", "state", "push") for command in calls) == 1
    assert not state.exists() and not models.exists() and not descriptor_path.exists()
    receipt = json.loads(
        (tmp_path / "application-state-adoption-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["remote_backend_authority_verified"] is True
    assert receipt["remote_state_lineage"] == "lineage"
    assert receipt["remote_state_serial"] == 3
    assert receipt["azure_resource_mutation_performed"] is False
    assert receipt["original_state_retained"] is True


def test_application_state_adoption_claim_resumes_verification_without_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }
    claim = {
        "schema_version": "fdai.application-state-adoption-claim.v1",
        "target_binding": context["target_binding"],
        "foundation_binding_digest": context["foundation_binding_digest"],
        "adoption_descriptor_digest": canonical_digest(descriptor),
        "staged_state_sha256": descriptor["staged_state_sha256"],
        "managed_resource_count": 1,
        "mutation_performed": False,
    }
    (tmp_path / "application-state-adoption-claim.json").write_text(
        json.dumps(claim), encoding="utf-8"
    )
    (tmp_path / "application-state-adoption-claim.json").chmod(0o600)

    def pull_state(_command: tuple[str, ...], **_kwargs: object) -> str:
        payload = json.loads(state.read_text())
        payload["serial"] += 1
        return json.dumps(payload)

    monkeypatch.setattr(standalone_host, "_capture", pull_state)
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("verification resume must not push state"),
    )

    standalone_host._adopt_application_state(
        tmp_path, context, descriptor, state, models, descriptor_path
    )

    assert (tmp_path / "application-state-adoption-receipt.json").is_file()


def test_application_state_adoption_rejects_occupied_or_mismatched_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }
    monkeypatch.setattr(standalone_host, "_capture", lambda *_args, **_kwargs: "occupied\n")
    with pytest.raises(ValueError, match="existence is invalid"):
        standalone_host._adopt_application_state(
            tmp_path, context, descriptor, state, models, descriptor_path
        )
    assert not (tmp_path / "application-state-adoption-claim.json").exists()

    monkeypatch.setattr(
        standalone_host,
        "_capture",
        lambda command, **_kwargs: (
            "false\n" if command[:4] == ("az", "storage", "blob", "exists") else "{}"
        ),
    )
    monkeypatch.setattr(standalone_host, "_run", lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match="differs"):
        standalone_host._adopt_application_state(
            tmp_path, context, descriptor, state, models, descriptor_path
        )
    assert (tmp_path / "application-state-adoption-claim.json").is_file()
    assert not (tmp_path / "application-state-adoption-receipt.json").exists()


def test_application_state_adoption_receipt_accepts_advanced_same_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }
    claim = {
        "schema_version": "fdai.application-state-adoption-claim.v1",
        "target_binding": context["target_binding"],
        "foundation_binding_digest": context["foundation_binding_digest"],
        "adoption_descriptor_digest": canonical_digest(descriptor),
        "staged_state_sha256": descriptor["staged_state_sha256"],
        "managed_resource_count": 1,
        "mutation_performed": False,
    }
    receipt = {
        "schema_version": "fdai.application-state-adoption-receipt.v1",
        "state": "adopted",
        "claim_digest": canonical_digest(claim),
        "remote_state_sha256": "c" * 64,
        "remote_state_lineage": "lineage",
        "remote_state_serial": 3,
        "managed_resource_count": 1,
        "remote_backend_authority_verified": True,
        "original_state_retained": True,
        "azure_resource_mutation_performed": False,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    (tmp_path / "application-state-adoption-receipt.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    (tmp_path / "application-state-adoption-receipt.json").chmod(0o600)
    monkeypatch.setattr(
        standalone_host,
        "_capture",
        lambda *_args, **_kwargs: json.dumps(
            {"version": 4, "serial": 9, "lineage": "lineage", "resources": []}
        ),
    )

    standalone_host._adopt_application_state(
        tmp_path, context, descriptor, state, models, descriptor_path
    )

    assert not state.exists() and not models.exists() and not descriptor_path.exists()


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
    monkeypatch.setattr(standalone_application, "_wait_for_approval_input", lambda _timeout: None)
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


def test_aks_stages_use_independent_roots_and_variables(tmp_path: Path) -> None:
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-aks",
        },
        "infra": str(tmp_path / "infra"),
        "runtime_infra": str(tmp_path / "cluster"),
        "database_infra": str(tmp_path / "database"),
        "workloads_infra": str(tmp_path / "workloads"),
    }

    assert standalone_host._stage_paths("runtime", context, tmp_path) == (
        tmp_path / "cluster",
        tmp_path / "runtime.auto.tfvars.json",
    )
    assert standalone_host._stage_paths("database", context, tmp_path) == (
        tmp_path / "database",
        tmp_path / "database.auto.tfvars.json",
    )
    assert standalone_host._stage_paths("application", context, tmp_path) == (
        tmp_path / "workloads",
        tmp_path / "workloads.auto.tfvars.json",
    )


def test_aks_operational_history_job_is_shadow_and_uses_inventory_identity() -> None:
    identity = {"resource_id": "inventory-resource", "client_id": "inventory-client"}
    job = standalone_host._aks_job(
        {"core-control-plane": "example.azurecr.io/core@sha256:" + "a" * 64},
        identity,
        ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"],
        "0 * * * *",
        {
            "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL": "https://example.invalid/history",
            "FDAI_OPERATIONAL_HISTORY_MODE": "shadow",
            "FDAI_OPERATIONAL_HISTORY_MAX_PARTITIONS": "32",
        },
        {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
        component="operational-history",
        deadline_seconds=1800,
        retry_limit=0,
    )

    assert job["identity_resource_id"] == identity["resource_id"]
    assert job["identity_client_id"] == identity["client_id"]
    assert job["environment"]["FDAI_OPERATIONAL_HISTORY_MODE"] == "shadow"
    assert "FDAI_OPERATIONAL_HISTORY_AUTHORITY_RECEIPT" not in job["environment"]
    assert job["secret_environment"] == {"FDAI_DATABASE_URL": "fdai-state-store-dsn"}
    assert job["retry_limit"] == 0


def test_aks_job_rejects_missing_core_image() -> None:
    with pytest.raises(TypeError, match="image is unavailable"):
        standalone_host._aks_job(
            {},
            {"resource_id": "inventory-resource", "client_id": "inventory-client"},
            ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"],
            "0 * * * *",
            {},
            {},
            component="operational-history",
            deadline_seconds=1800,
        )


def test_postgres_aks_substrate_excludes_flexible_server() -> None:
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-aks",
        }
    }

    targets = standalone_host._substrate_targets(context)

    assert "module.state_store" not in targets
    assert "azurerm_key_vault_secret.state_store_dsn" not in targets
    assert "azurerm_role_assignment.inventory_kv_secrets_user" not in targets
    assert "module.event_bus" in targets
    assert "module.key_vault" in targets


def test_aks_substrate_includes_document_dependencies_without_container_apps() -> None:
    targets = set(
        standalone_host._substrate_targets(
            {
                "runtime_profile": {
                    "runtime_platform": "aks",
                    "database_placement": "postgres-flex",
                }
            }
        )
    )

    assert {
        "module.ingestion_identity",
        "module.ingestion_worker_identity",
        "module.document_storage",
        "azurerm_key_vault_secret.ingestion_api_dsn",
        "azurerm_key_vault_secret.ingestion_worker_dsn",
        "azurerm_role_assignment.ingestion_aks_eventhubs_sender",
        "azurerm_role_assignment.ingestion_worker_aks_eventhubs_receiver",
        "azurerm_role_assignment.inventory_reader",
        "azurerm_role_assignment.inventory_monitoring_reader",
        "azurerm_role_assignment.inventory_log_analytics_reader",
        "azurerm_role_assignment.inventory_cost_reader",
        "azurerm_role_assignment.inventory_kubernetes_reader",
        "azurerm_role_assignment.inventory_stage_sender",
    } <= targets
    assert "module.ingestion_gateway" not in targets


@pytest.mark.parametrize("existing", [False, True])
def test_aks_kubeconfig_uses_explicit_host_identity(tmp_path, monkeypatch, existing):
    tmp_path.chmod(0o700)
    kubeconfig = tmp_path / "aks.kubeconfig"
    if existing:
        kubeconfig.write_text("prior kubeconfig")
        kubeconfig.chmod(0o600)
    context = {
        "client_id": "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kubeconfig.stat().st_mode & 0o777 == 0o600
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] in (60, 180)
        kubeconfig.write_text("generated kubeconfig")

    monkeypatch.setattr(standalone_host, "_run", run)
    reads = []

    def capture(command, **kwargs):
        reads.append(command)
        assert command[:3] == ("kubectl", "config", "view")
        assert "--minify" in command and "--raw" not in command
        return json.dumps(
            {
                "users": [
                    {
                        "user": {
                            "exec": {
                                "command": "kubelogin",
                                "args": [
                                    "get-token",
                                    "--login",
                                    "msi",
                                    "--client-id",
                                    context["client_id"],
                                ],
                            }
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(standalone_host, "_capture", capture)
    assert (
        standalone_host._prepare_aks_kubeconfig(
            context, tmp_path, resource_group="example-group", cluster_name="example-cluster"
        )
        == kubeconfig
    )
    assert commands[0][commands[0].index("--subscription") + 1] == context["subscription_id"]
    assert "--admin" not in commands[0]
    assert len(reads) == 1
    assert commands[1] == (
        "kubelogin",
        "convert-kubeconfig",
        "--kubeconfig",
        str(kubeconfig),
        "--login",
        "msi",
        "--client-id",
        context["client_id"],
    )


@pytest.mark.parametrize("failure", ["link", "public-file", "missing-client", "convert"])
def test_aks_kubeconfig_fails_closed(tmp_path, monkeypatch, failure):
    tmp_path.chmod(0o700)
    kubeconfig = tmp_path / "aks.kubeconfig"
    if failure == "link":
        kubeconfig.symlink_to(tmp_path / "missing")
    elif failure == "public-file":
        kubeconfig.write_text("unsafe config")
        kubeconfig.chmod(0o644)
    context = {
        "client_id": "" if failure == "missing-client" else "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[0] == "kubelogin":
            raise ValueError("conversion failed")
        kubeconfig.write_text("generated")

    monkeypatch.setattr(standalone_host, "_run", run)
    with pytest.raises((ValueError, OSError)):
        standalone_host._prepare_aks_kubeconfig(
            context, tmp_path, resource_group="example-group", cluster_name="example-cluster"
        )
    assert len(commands) == (2 if failure == "convert" else 0)


@pytest.mark.parametrize(
    "authentication", ["devicecode", "wrong-client", "duplicate", "secret", "multiple-users", "env"]
)
def test_aks_kubeconfig_readback_rejects_wrong_authentication(
    tmp_path, monkeypatch, authentication
):
    tmp_path.chmod(0o700)
    client = "00000000-0000-0000-0000-000000000001"
    context = {"client_id": client, "subscription_id": "00000000-0000-0000-0000-000000000002"}
    user = {
        "exec": {
            "command": "kubelogin",
            "args": ["get-token", "--login", "msi", "--client-id", client],
        }
    }
    if authentication == "devicecode":
        user["exec"]["args"][2] = "devicecode"
    elif authentication == "wrong-client":
        user["exec"]["args"][-1] = "unselected-client"
    elif authentication == "duplicate":
        user["exec"]["args"].extend(["--login", "devicecode"])
    elif authentication == "secret":
        user["token"] = "synthetic-test-token"
    elif authentication == "env":
        user["exec"]["env"] = [{"name": "AZURE_CLIENT_ID", "value": "other"}]
    users = [{"user": user}] * (2 if authentication == "multiple-users" else 1)
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda *_args, **_kwargs: (tmp_path / "aks.kubeconfig").write_text("config"),
    )
    monkeypatch.setattr(
        standalone_host, "_capture", lambda *_args, **_kwargs: json.dumps({"users": users})
    )
    with pytest.raises(ValueError, match="AKS authentication"):
        standalone_host._prepare_aks_kubeconfig(
            context, tmp_path, resource_group="example-group", cluster_name="example-cluster"
        )


def test_aks_workload_binds_digest_image_and_additional_identity() -> None:
    digest = "a" * 64
    workload = standalone_host._aks_workload(
        "operator",
        {"operator-service": f"example.azurecr.io/operator-service@sha256:{digest}"},
        {"resource_id": "/identities/operator", "client_id": "operator-client"},
        {"RUNTIME_ENV": "dev"},
        {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
        "/healthz",
        "/healthz",
        external=True,
        additional_identities={
            "command": {
                "resource_id": "/identities/command",
                "client_id": "command-client",
            }
        },
    )

    assert workload["image"] == (f"example.azurecr.io/operator-service@sha256:{digest}")
    assert workload["external"] is True
    assert workload["environment"]["FDAI_DATABASE_ROLE"] == "fdai_operator"
    assert workload["environment"]["PGOPTIONS"] == "-c role=fdai_operator"
    assert workload["environment"]["FDAI_EXECUTION_VENUE"] == "deployed"
    assert workload["additional_identities"] == {
        "command": {
            "resource_id": "/identities/command",
            "client_id": "command-client",
        }
    }


def test_aks_core_semantic_environment_binds_topics_and_enabled_model() -> None:
    digest = "a" * 64
    environment = standalone_host._aks_core_semantic_environment(
        application_values={"enable_llm": True},
        substrate_outputs={
            "semantic_physical": "fdai.pantheon.objects",
            "llm_endpoint": "https://example.openai.azure.com/",
            "llm_model_endpoints": {"azure-openai:example": "https://example.openai.azure.com/"},
            "resolved_models_sha256": digest,
        },
        semantic_topics=[
            "operator.semantic-turn.requests",
            "core.semantic-turn.projections",
            "operator.read-investigation.requests",
        ],
    )

    assert environment == {
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.read-investigation.requests",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
        "LLM_MODE": "azure",
        "LLM_RESOLVED_MODELS_PATH": "/app/resolved-models.json",
        "LLM_RESOLVED_MODELS_SHA256": digest,
        "FDAI_LLM_ENDPOINT": "https://example.openai.azure.com/",
        "FDAI_MODEL_ENDPOINTS_JSON": (
            '{"azure-openai:example":"https://example.openai.azure.com/"}'
        ),
    }


def test_aks_core_semantic_environment_keeps_transport_when_model_is_disabled() -> None:
    environment = standalone_host._aks_core_semantic_environment(
        application_values={"enable_llm": False},
        substrate_outputs={"semantic_physical": "fdai.pantheon.objects"},
        semantic_topics=["requests", "projections", "investigations"],
    )

    assert environment == {
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "projections",
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "investigations",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
    }


@pytest.mark.parametrize(
    ("substrate_update", "message"),
    [
        ({"llm_endpoint": ""}, "LLM endpoint"),
        ({"llm_model_endpoints": {}}, "model endpoint outputs"),
        ({"resolved_models_sha256": "invalid"}, "lowercase SHA-256"),
    ],
)
def test_aks_core_semantic_environment_rejects_incomplete_enabled_model(
    substrate_update: dict[str, object], message: str
) -> None:
    substrate_outputs: dict[str, object] = {
        "semantic_physical": "physical",
        "llm_endpoint": "https://example.openai.azure.com/",
        "llm_model_endpoints": {"azure-openai:example": "https://example.openai.azure.com/"},
        "resolved_models_sha256": "a" * 64,
        **substrate_update,
    }

    with pytest.raises(ValueError, match=message):
        standalone_host._aks_core_semantic_environment(
            application_values={"enable_llm": True},
            substrate_outputs=substrate_outputs,
            semantic_topics=["requests", "projections", "investigations"],
        )


def test_prepare_aks_application_requires_core_semantic_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("runtime-receipt.json", "image-import-receipt.json", "migration-receipt.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
        },
        "infra": str(tmp_path / "infra"),
        "runtime_infra": str(tmp_path / "runtime"),
        "tenant_id": "tenant",
        "subscription_id": "subscription",
    }
    application = {"enable_llm": True, "region": "westus2", "env": "dev"}
    identities = {
        name: {"resource_id": f"/identities/{name}", "client_id": f"{name}-client"}
        for name in (
            "core",
            "operator",
            "command",
            "executor",
            "inventory",
            "canary",
            "ingestion",
            "ingestion_worker",
        )
    }
    semantic_topics = ["requests", "projections", "investigations"]

    def private_json(path: Path, _label: str) -> dict[str, object]:
        return context if path.name == "context.json" else application

    def json_output(_infra: Path, name: str) -> object:
        return {
            "runtime_identity_bindings": identities,
            "event_bus_topics": ["events"],
            "event_bus_semantic_topics": semantic_topics,
            "llm_model_endpoints": {"model": "endpoint"},
        }.get(name, {})

    def require_semantic_environment(**kwargs: object) -> dict[str, str]:
        assert kwargs["application_values"] == application
        assert kwargs["semantic_topics"] == semantic_topics
        outputs = kwargs["substrate_outputs"]
        assert isinstance(outputs, dict)
        assert outputs["semantic_physical"] == "event_bus_semantic_physical_topic"
        assert outputs["llm_endpoint"] == "llm_endpoint"
        assert outputs["llm_model_endpoints"] == {"model": "endpoint"}
        assert outputs["resolved_models_sha256"] == "resolved_models_sha256"
        raise RuntimeError("core semantic environment required")

    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_: None)
    monkeypatch.setattr(
        standalone_host,
        "_terraform_output",
        lambda _infra, name: name,
    )
    monkeypatch.setattr(standalone_host, "_terraform_json_output", json_output)
    monkeypatch.setattr(
        standalone_host,
        "_prepare_aks_kubeconfig",
        lambda *_args, **_kwargs: tmp_path / "aks.kubeconfig",
    )
    monkeypatch.setattr(
        standalone_host,
        "_aks_core_semantic_environment",
        require_semantic_environment,
    )

    with pytest.raises(RuntimeError, match="core semantic environment required"):
        standalone_host._prepare_aks_application(SimpleNamespace(), tmp_path)


def test_aks_document_workloads_bind_complete_service_contracts() -> None:
    digest = "a" * 64
    refs = {
        name: f"example.azurecr.io/{name}@sha256:{digest}"
        for name in ("document-ingestion-api", "document-processing-worker", "clamav")
    }
    application = {
        "env": "dev",
        "tenant_id": "tenant",
        "operator_api_audience": "audience",
        "rbac_readers_group_id": "readers",
        "rbac_contributors_group_id": "contributors",
        "rbac_approvers_group_id": "approvers",
        "rbac_owners_group_id": "owners",
        "rbac_break_glass_group_id": "break-glass",
        "ingestion_cors_allow_origins": "https://localhost",
    }
    workloads = standalone_host._aks_document_workloads(
        refs=refs,
        ingestion_identity={"resource_id": "/identities/api", "client_id": "api-client"},
        worker_identity={"resource_id": "/identities/worker", "client_id": "worker-client"},
        application_values=application,
        kafka="example.servicebus.windows.net:9093",
        postgres_fqdn="example.postgres.database.azure.com",
        document_store={
            "account_name": "documents",
            "account_url": "https://documents.dfs.core.windows.net/",
            "source_file_system": "documents",
            "derived_file_system": "derived",
        },
        document_topics={
            "pipeline_stages": "fdai.pipeline.stages",
            "pantheon_objects": "fdai.pantheon.objects",
        },
    )

    assert set(workloads) == {"document-ingestion-api", "document-processing-worker"}
    api = workloads["document-ingestion-api"]
    worker = workloads["document-processing-worker"]
    assert api["environment"]["FDAI_DATABASE_ROLE"] == "fdai_ingestion_api"
    assert api["environment"]["FDAI_DOCUMENT_RETRIEVAL_MODE"] == "lexical"
    assert api["environment"]["FDAI_INGESTION_CORS_ALLOW_ORIGINS"] == "https://localhost"
    assert worker["environment"]["FDAI_DATABASE_ROLE"] == "fdai_ingestion_worker"
    assert worker["environment"]["FDAI_CLAMAV_HOST"] == "127.0.0.1"
    assert worker["sidecars"]["clamav"]["image"] == refs["clamav"]
    assert worker["sidecars"]["clamav"]["writable_paths"]["database"] == {
        "mount_path": "/var/lib/clamav",
        "size_limit": "1Gi",
    }


@pytest.mark.parametrize(
    ("component", "service", "role"),
    [
        ("operator", "operator-service", "fdai_operator"),
        ("executor", "isolated-executor", "fdai_executor"),
        ("ingestion", "document-ingestion-api", "fdai_ingestion_api"),
        ("worker", "document-processing-worker", "fdai_ingestion_worker"),
    ],
)
def test_aks_workload_preserves_service_database_role(component, service, role) -> None:
    environment = {"RUNTIME_ENV": "dev", "FDAI_DATABASE_ROLE": "wrong-role", "PGOPTIONS": ""}
    workload = standalone_host._aks_workload(
        component,
        {service: f"example.com/{service}@sha256:{'a' * 64}"},
        {"resource_id": f"/identities/{component}", "client_id": f"{component}-client"},
        environment,
        {},
        "/ready",
        "/live",
    )

    assert workload["environment"]["FDAI_DATABASE_ROLE"] == role
    assert workload["environment"]["PGOPTIONS"] == f"-c role={role}"
    assert workload["environment"]["FDAI_EXECUTION_VENUE"] == "deployed"
    assert "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER" not in workload["environment"]
    assert environment == {
        "RUNTIME_ENV": "dev",
        "FDAI_DATABASE_ROLE": "wrong-role",
        "PGOPTIONS": "",
    }


@pytest.mark.parametrize(
    "missing_service",
    [
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        None,
    ],
)
def test_aks_application_readback_requires_complete_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_service: str | None
) -> None:
    kubeconfig = tmp_path / "aks.kubeconfig"
    kubeconfig.write_text("test configuration", encoding="utf-8")
    expected = {
        name: {"image": f"example.com/{name}@sha256:{'a' * 64}", "replicas": 2}
        for name in (
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
        )
        if name != missing_service
    }
    observations: list[str] = []
    health_checks: list[dict[str, object]] = []

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        observations.append(command[2])
        return "observed-json"

    def verify_health(**kwargs: object) -> bool:
        health_checks.append(kwargs)
        return True

    monkeypatch.setattr(standalone_host, "_capture", capture)
    monkeypatch.setattr(standalone_host, "verify_workload_health", verify_health)
    context = {
        "runtime_profile": {"runtime_platform": "aks", "database_placement": "postgres-flex"},
        "kubeconfig": str(kubeconfig),
        "expected_workloads": expected,
        "source_commit": "c" * 40,
    }

    assert standalone_host._readback_stage("application", context) is (missing_service is None)
    if missing_service is None:
        assert observations == ["deployments", "pods"]
        assert health_checks == [
            {
                "deployments": "observed-json",
                "pods": "observed-json",
                "expected": expected,
                "source_commit": "c" * 40,
            }
        ]
    else:
        assert observations == []
        assert health_checks == []


def test_database_plan_requires_cluster_and_image_receipts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="database plan prerequisites"):
        standalone_host._plan(SimpleNamespace(stage="database"), tmp_path)


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
