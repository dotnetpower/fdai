"""Residual image recovery cannot rerun completed infrastructure or expand the original scope."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_runner_image_recovery as recovery  # noqa: E402
import genesis_runner_image_recovery_plan as planner  # noqa: E402
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from genesis_runner_image_contract import _EXPECTED_RESOURCE_TYPES  # noqa: E402


@pytest.fixture
def plans():
    original = {"resource_changes": []}
    current = {"errored": False, "complete": True, "applyable": True, "resource_changes": []}
    for address, kind in {**_EXPECTED_RESOURCE_TYPES, recovery._READ: "azapi_resource"}.items():
        mode = "data" if address == recovery._READ else "managed"
        after = {"name": address, "nested": [{"pinned": "original", "computed": None}]}
        entry = {
            "address": address,
            "mode": mode,
            "type": kind,
            "change": {
                "actions": ["create"],
                "before": None,
                "after": after,
                "after_unknown": {"nested": [{"computed": True}]},
            },
        }
        original["resource_changes"].append(deepcopy(entry))
        if address == recovery._WAIT:
            entry["change"].update(actions=["delete", "create"], before=deepcopy(after))
        elif address == recovery._READ:
            entry["change"].update(actions=["read"])
        elif address not in recovery._PENDING:
            entry["change"].update(actions=["no-op"], before=deepcopy(after))
        else:
            entry["change"]["after"]["nested"][0]["computed"] = "resolved"
        current["resource_changes"].append(entry)
    return original, current


def test_residual_plan_only_finalizes_pending_work(plans):
    original, current = plans
    result = recovery.validate_residual_plan(current, original)
    assert result["preserved_managed_count"] == 23
    assert set(result["remaining_addresses"]) == recovery._PENDING | {recovery._WAIT}
    assert result["apply_authorized"] is False
    assert result["deployment_ready"] is False


@pytest.mark.parametrize("actions", [["create"], ["update"], ["delete"], ["delete", "create"]])
def test_residual_plan_never_repeats_completed_work(plans, actions):
    original, current = plans
    entry = next(
        item
        for item in current["resource_changes"]
        if item["address"] == "azurerm_linux_virtual_machine.builder"
    )
    entry["change"]["actions"] = actions
    with pytest.raises(ValueError, match="completed work"):
        recovery.validate_residual_plan(current, original)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "duplicate",
        "extra",
        "mode",
        "type",
        "drift",
        "deferred",
        "errored",
        "incomplete",
        "check",
        "changed-intent",
        "present-image",
        "changed-noop",
    ],
)
def test_residual_plan_rejects_ambiguous_or_expanded_plan(plans, corruption):
    original, current = plans
    if corruption == "missing":
        current["resource_changes"].pop()
    elif corruption == "duplicate":
        current["resource_changes"].append(deepcopy(current["resource_changes"][0]))
    elif corruption == "extra":
        entry = deepcopy(current["resource_changes"][0])
        entry["address"] = "azurerm_resource_group.unselected"
        current["resource_changes"].append(entry)
    elif corruption in {"mode", "type"}:
        current["resource_changes"][0][corruption] = "changed"
    elif corruption in {"drift", "deferred"}:
        current["resource_drift" if corruption == "drift" else "deferred_changes"] = [{}]
    elif corruption == "errored":
        current["errored"] = True
    elif corruption == "incomplete":
        current["complete"] = False
    elif corruption == "check":
        current["checks"] = [{"status": "fail"}]
    else:
        address = (
            "azurerm_image.runner"
            if corruption != "changed-noop"
            else "azurerm_linux_virtual_machine.builder"
        )
        entry = next(item for item in current["resource_changes"] if item["address"] == address)
        if corruption == "present-image":
            entry["change"]["before"] = {}
        else:
            entry["change"]["after"]["nested"][0]["pinned"] = "changed"
    with pytest.raises(ValueError):
        recovery.validate_residual_plan(current, original)


@pytest.fixture
def planning_inputs(tmp_path, monkeypatch, plans):
    original_plan, residual = plans
    foundation = tmp_path / "foundation"
    original = foundation / "runner-image-attempt-1"
    root = original / "root"
    root.mkdir(mode=0o700, parents=True)
    foundation.chmod(0o700)
    original.chmod(0o700)
    write_private_bytes(foundation / "source-execution.lock", b"")
    old = (
        (ROOT / "infra/genesis-runner-image/main.tf")
        .read_bytes()
        .replace(b"$(az vm get-instance-view", b'$("$AZ_CLI" vm get-instance-view')
        .replace(
            b"      VM_ID = azurerm_linux_virtual_machine.builder.id",
            b'      AZ_CLI = abspath("/usr/bin/az")\n'
            b"      VM_ID  = azurerm_linux_virtual_machine.builder.id",
        )
    )
    write_private_bytes(root / "main.tf", old)
    state = {"version": 4, "serial": 25, "lineage": "synthetic-lineage", "resources": []}
    write_private_bytes(root / "terraform.tfstate", canonical_bytes(state))
    variables = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    write_private_bytes(original / "runner-image.auto.tfvars.json", canonical_bytes(variables))
    write_private_bytes(original / planner.PLAN_JSON_NAME, canonical_bytes(original_plan))
    review = {
        "variables_digest": canonical_digest(variables),
        "terraform_root_digest": planner.hash_tree(root),
        "profile_digest": canonical_digest({}),
        "terraform_digest": "f" * 64,
        "source_commit": "a" * 40,
        "target_binding": compute_target_binding(**variables),
        "review_digest": "d" * 64,
        "plan_digest": "e" * 64,
        "plan_json_digest": hashlib.sha256(canonical_bytes(original_plan)).hexdigest(),
    }
    monkeypatch.setattr(planner, "load_review", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(
        planner.image, "_load_apply_claim", lambda *_args, **_kwargs: {"state": "applying"}
    )
    monkeypatch.setattr(
        planner,
        "load_profile",
        lambda *_args: SimpleNamespace(
            to_mapping=lambda: {}, environment="dev", transport="manual"
        ),
    )
    monkeypatch.setattr(planner, "active_azure_target", lambda: SimpleNamespace(**variables))
    monkeypatch.setattr(
        planner,
        "inspect_source",
        lambda *_args: SimpleNamespace(commit="b" * 40, reverify=lambda: None),
    )
    monkeypatch.setattr(planner.image, "_trusted_terraform", lambda value: value)
    monkeypatch.setattr(planner.image, "_file_digest", lambda *_args: "f" * 64)
    monkeypatch.setattr(planner.image, "_terraform_environment", lambda *_args, **_kwargs: {})

    def snapshot(_source, destination, **_kwargs):
        destination.mkdir(mode=0o700)
        write_private_bytes(
            destination / "main.tf", (ROOT / "infra/genesis-runner-image/main.tf").read_bytes()
        )
        return planner.hash_tree(destination)

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "apply" not in command
        assert kwargs["timeout"] <= 60
        if command[1] == "plan":
            assert f"-state={root / 'terraform.tfstate'}" in command
            assert "-lock-timeout=0s" in command
            destination = Path(next(value[5:] for value in command if value.startswith("-out=")))
            write_private_bytes(destination, b"saved residual plan")
        return subprocess.CompletedProcess(
            command, 0, json.dumps(residual) if command[1] == "show" else "", ""
        )

    monkeypatch.setattr(planner, "snapshot_terraform_root", snapshot)
    monkeypatch.setattr(planner, "run_with_heartbeat", run)
    arguments = dict(
        repository_root=tmp_path / "repository",
        original_directory=original,
        work_dir=tmp_path / "recovery",
        expected_review_digest="d" * 64,
        terraform=tmp_path / "terraform",
        timeout_seconds=60,
    )
    return arguments, calls, root, residual


def test_recovery_planner_preserves_authoritative_state_and_never_applies(planning_inputs):
    args, calls, root, _ = planning_inputs
    before = (root / "terraform.tfstate").read_bytes()
    result = planner.prepare_recovery_plan(**args)
    assert result["apply_authorized"] is False
    assert result["original_state_unchanged"] is True
    assert result["source_commit"] != result["recovery_source_commit"]
    assert (root / "terraform.tfstate").read_bytes() == before
    assert not list(args["work_dir"].rglob("terraform.tfstate"))
    assert [command[1] for command in calls] == ["init", "validate", "plan", "show"]
    with pytest.raises(FileExistsError):
        planner.prepare_recovery_plan(**args)


def test_recovery_planner_refuses_competing_source_execution(planning_inputs):
    args, calls, root, _ = planning_inputs
    descriptor = os.open(root.parent.parent / "source-execution.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="another source execution"):
            planner.prepare_recovery_plan(**args)
    finally:
        os.close(descriptor)
    assert not calls


def test_recovery_planner_retains_blocked_plan_without_ready_review(planning_inputs):
    args, _, _, residual = planning_inputs
    residual["resource_changes"][0]["change"]["actions"] = ["delete"]
    with pytest.raises(ValueError):
        planner.prepare_recovery_plan(**args)
    assert (args["work_dir"] / "blocked.json").is_file()
    assert not (args["work_dir"] / "residual-review.json").exists()


def test_recovery_planner_rejects_extra_configuration_change(planning_inputs, monkeypatch):
    args, calls, _, _ = planning_inputs
    original = planner.snapshot_terraform_root

    def changed(*positional, **keywords):
        digest = original(*positional, **keywords)
        with (positional[1] / "main.tf").open("ab") as output:
            output.write(b"\nchanged input\n")
        return digest

    monkeypatch.setattr(planner, "snapshot_terraform_root", changed)
    with pytest.raises(ValueError, match="beyond the trusted CLI"):
        planner.prepare_recovery_plan(**args)
    assert not calls
