"""Residual image recovery cannot rerun completed infrastructure or expand the original scope."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_runner_image_recovery as recovery  # noqa: E402
import genesis_runner_image_recovery_apply as executor  # noqa: E402
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


@pytest.mark.parametrize("change", ["computed", "empty", "set-order", "known", "identity"])
def test_residual_refresh_only_accepts_proven_computed_or_equivalent_fields(plans, change):
    original, current = plans
    address = "azurerm_firewall.builder"
    planned = next(item for item in current["resource_changes"] if item["address"] == address)
    intended = next(item for item in original["resource_changes"] if item["address"] == address)
    before = {"id": "original-resource", "field": None}
    after = {"id": "original-resource", "field": []}
    if change == "computed":
        intended["change"]["after_unknown"]["field"] = True
        after["field"] = ["resolved-link"]
    elif change == "set-order":
        before = {
            "id": "original-resource",
            "application_rule_collection": [{"priority": 100}, {"priority": 200}],
        }
        after = {
            "id": "original-resource",
            "application_rule_collection": [{"priority": 200}, {"priority": 100}],
        }
    elif change == "known":
        after["field"] = ["changed-rule"]
    elif change == "identity":
        after["id"] = "other-resource"
    planned["change"].update(before=deepcopy(after), after=deepcopy(after))
    current["resource_drift"] = [
        {
            "address": address,
            "mode": "managed",
            "type": planned["type"],
            "change": {"actions": ["update"], "before": before, "after": after},
        }
    ]
    if change in {"known", "identity"}:
        with pytest.raises(ValueError):
            recovery.validate_residual_plan(current, original)
    else:
        assert recovery.validate_residual_plan(current, original)["verified_refresh_count"] == 1


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
        planner.image,
        "_load_apply_claim",
        lambda *_args, **_kwargs: {"state": "applying", "executor_identity_digest": "e" * 64},
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
    monkeypatch.setattr(planner.image, "_execution_tree_digest", lambda *_args: "f" * 64)
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


def test_recovery_planner_detects_state_change_before_review(planning_inputs, monkeypatch):
    args, _, root, _ = planning_inputs
    original = planner.run_with_heartbeat

    def changed(command, **kwargs):
        result = original(command, **kwargs)
        if command[1] == "plan":
            (root / "terraform.tfstate").write_bytes(b"concurrently changed state")
        return result

    monkeypatch.setattr(planner, "run_with_heartbeat", changed)
    with pytest.raises(ValueError, match="evidence changed"):
        planner.prepare_recovery_plan(**args)
    assert not (args["work_dir"] / "residual-review.json").exists()


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


@pytest.mark.skipif(shutil.which("terraform") is None, reason="local Terraform executable required")
def test_saved_residual_plan_applies_to_original_local_state_only(tmp_path):
    terraform = shutil.which("terraform")
    assert terraform is not None
    original = tmp_path / "original"
    corrected = tmp_path / "corrected"
    original.mkdir()
    corrected.mkdir()
    initial = 'resource "terraform_data" "original" { input = "unchanged" }\n'
    (original / "main.tf").write_text(initial)
    (corrected / "main.tf").write_text(
        initial + 'resource "terraform_data" "remaining" { input = "new" }\n'
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(("TF_", "ARM_"))
    }

    def run(directory, *arguments):
        subprocess.run(  # noqa: S603
            [terraform, f"-chdir={directory}", *arguments],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=30,
        )

    run(original, "init", "-backend=false", "-input=false")
    run(original, "apply", "-input=false", "-auto-approve")
    state_path = original / "terraform.tfstate"
    prior = json.loads(state_path.read_bytes())
    run(corrected, "init", "-backend=false", "-input=false")
    run(corrected, "plan", "-input=false", f"-state={state_path}", "-out=residual.tfplan")
    assert json.loads(state_path.read_bytes()) == prior
    run(corrected, "apply", "-input=false", f"-state={state_path}", "residual.tfplan")
    after = json.loads(state_path.read_bytes())
    assert after["lineage"] == prior["lineage"]
    assert after["serial"] > prior["serial"]
    assert len(after["resources"]) == 2
    original_record = next(entry for entry in after["resources"] if entry["name"] == "original")
    assert (
        original_record["instances"][0]["attributes"]["id"]
        == prior["resources"][0]["instances"][0]["attributes"]["id"]
    )
    assert not (corrected / "terraform.tfstate").exists()


@pytest.fixture
def execution_inputs(planning_inputs, monkeypatch):
    arguments, _, root, _ = planning_inputs
    review = planner.prepare_recovery_plan(**arguments)
    work = arguments["work_dir"]
    moment = datetime.now(UTC)
    approval = {
        "schema_version": "fdai.genesis-approval.v1",
        "run_binding": review["review_digest"],
        "source_commit": "b" * 40,
        "stage": "runner-image",
        "approved": True,
        "approved_at": moment.isoformat(),
        "expires_at": (moment + timedelta(minutes=30)).isoformat(),
        "actor_digest": "c" * 64,
        "evidence": {
            "review_digest": review["review_digest"],
            "plan_digest": review["plan_digest"],
        },
    }
    approval_path = work / "approval.json"
    write_private_bytes(approval_path, canonical_bytes(approval))
    calls = []
    failure = {"apply": False}
    monkeypatch.setattr(executor, "load_review", planner.load_review)
    monkeypatch.setattr(executor, "active_azure_target", planner.active_azure_target)
    monkeypatch.setattr(
        executor,
        "inspect_source",
        lambda *_args, **_kwargs: SimpleNamespace(commit="b" * 40, reverify=lambda: None),
    )
    monkeypatch.setattr(executor, "current_actor_digest", lambda *_args: "c" * 64)
    monkeypatch.setattr(
        executor,
        "GenesisChecks",
        lambda *_args, **_kwargs: SimpleNamespace(
            verify_source=lambda **_values: calls.append("source-ci")
        ),
    )

    def run(command, **_kwargs):
        assert command[1] == "apply"
        assert f"-state={root / 'terraform.tfstate'}" in command
        assert command[-1] == str(work / "residual.tfplan")
        claim = json.loads((work / "residual-apply-claim.json").read_bytes())
        assert claim["approver_actor_digest"] == "c" * 64
        assert claim["executor_identity_digest"] == "e" * 64
        assert claim["idempotency_key"]
        calls.append("apply")
        state = json.loads((root / "terraform.tfstate").read_bytes())
        state["serial"] += 1
        (root / "terraform.tfstate").write_bytes(canonical_bytes(state))
        return subprocess.CompletedProcess(command, 1 if failure["apply"] else 0, "", "")

    def observe(**_kwargs):
        calls.append("observe")
        return "/synthetic/image"

    monkeypatch.setattr(executor, "run_with_heartbeat", run)
    monkeypatch.setattr(
        executor.image,
        "_capture",
        lambda *_args, **_kwargs: '{"runner_registered":false,"subscription_ready":false}',
    )
    monkeypatch.setattr(executor, "verify_runner_image_effect", observe)
    monkeypatch.setattr(
        executor.image, "_verify_zero_change", lambda **_kwargs: calls.append("zero-change")
    )
    return (
        {
            **arguments,
            "expected_review_digest": review["review_digest"],
            "repository": "example/fdai",
            "approval_file": approval_path,
            "timeout_seconds": 900,
        },
        calls,
        failure,
    )


def test_residual_apply_claim_precedes_effect_and_resume_only_observes(execution_inputs):
    arguments, calls, _ = execution_inputs
    receipt = executor.apply_recovery(**arguments)
    assert receipt["effect_verified"] is True
    assert receipt["deployment_ready"] is False
    assert "runner_image_id" not in receipt
    assert calls == ["source-ci", "apply", "observe", "zero-change"]
    with pytest.raises(ValueError, match="never repeat"):
        executor.apply_recovery(**arguments)
    assert calls.count("apply") == 1
    assert (
        executor.apply_recovery(**{**arguments, "verify_only": True, "approval_file": None})
        == receipt
    )
    assert calls.count("apply") == 1


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-approval",
        "other-plan",
        "other-source",
        "other-actor",
        "expired",
        "state",
        "plan",
        "configuration",
    ],
)
def test_residual_apply_rejects_changed_context_before_effect(execution_inputs, invalid):
    arguments, calls, _ = execution_inputs
    work = arguments["work_dir"]
    if invalid == "missing-approval":
        arguments["approval_file"] = None
    elif invalid in {"state", "plan", "configuration"}:
        path = {
            "state": arguments["original_directory"] / "root/terraform.tfstate",
            "plan": work / "residual.tfplan",
            "configuration": work / "root/main.tf",
        }[invalid]
        if invalid == "state":
            state = json.loads(path.read_bytes())
            state["serial"] += 1
            path.write_bytes(canonical_bytes(state))
        else:
            path.write_bytes(b"changed")
    else:
        path = arguments["approval_file"]
        value = json.loads(path.read_bytes())
        if invalid == "other-plan":
            value["evidence"]["plan_digest"] = "f" * 64
        elif invalid == "other-source":
            value["source_commit"] = "f" * 40
        elif invalid == "other-actor":
            value["actor_digest"] = "f" * 64
        else:
            value["approved_at"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
            value["expires_at"] = (datetime.now(UTC) - timedelta(hours=1, minutes=30)).isoformat()
        path.write_bytes(canonical_bytes(value))
    with pytest.raises(ValueError):
        executor.apply_recovery(**arguments)
    assert "apply" not in calls
    assert not (work / "residual-apply-claim.json").exists()


def test_failed_residual_apply_never_reexecutes(execution_inputs):
    arguments, calls, failure = execution_inputs
    failure["apply"] = True
    with pytest.raises(ValueError, match="preserve the claim"):
        executor.apply_recovery(**arguments)
    with pytest.raises(ValueError, match="never repeat"):
        executor.apply_recovery(**arguments)
    assert calls.count("apply") == 1
    assert "observe" not in calls
    assert not (arguments["work_dir"] / "residual-apply-receipt.json").exists()


def test_residual_verification_rejects_tampered_claim_identity(execution_inputs):
    arguments, calls, _ = execution_inputs
    executor.apply_recovery(**arguments)
    claim_path = arguments["work_dir"] / "residual-apply-claim.json"
    claim = json.loads(claim_path.read_bytes())
    claim["approver_actor_digest"] = claim["credential_actor_digest"] = "invalid"
    claim_path.write_bytes(canonical_bytes(claim))
    calls.clear()
    with pytest.raises(ValueError, match="schema or identity"):
        executor.apply_recovery(**{**arguments, "verify_only": True, "approval_file": None})
    assert "apply" not in calls
    assert "observe" not in calls
