"""Exact approval and retained-claim boundaries for Foundation recovery execution."""

from __future__ import annotations

import fcntl
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_foundation_recovery_apply as recovery  # noqa: E402
import genesis_foundation_recovery_handoff as handover  # noqa: E402
import genesis_foundation_recovery_successor as successor  # noqa: E402
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from tests.integration.scripts.test_genesis_foundation import recovery_plans  # noqa: E402, F401

__all__ = ["recovery_plans"]


@pytest.mark.parametrize("defect", [None, "concurrent-state", "existing-group", "expanded-role"])
def test_successor_planner_preserves_original_state_owner(
    tmp_path, monkeypatch, successor_plans, defect
):
    from tests.integration.scripts.test_genesis_foundation import (
        test_foundation_recovery_planner_never_applies_or_copies_state,
    )

    test_foundation_recovery_planner_never_applies_or_copies_state(
        tmp_path,
        monkeypatch,
        None,
        defect,
        successor_case=successor_plans,
    )


@pytest.fixture
def successor_plans():
    import copy

    role_ids = [
        f"/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/00000000-0000-0000-0000-{number:012d}"
        for number in (1, 2, 3)
    ]
    condition = " ".join(role_ids * 2) + " ServicePrincipal"
    values = {
        successor.APPLICATION: {"name": "retained", "id": "synthetic-group"},
        successor.VM: {
            "os_disk": [
                {
                    "caching": "ReadWrite",
                    "diff_disk_settings": [{"option": "Local", "placement": "ResourceDisk"}],
                }
            ]
        },
        successor.DELEGATE: {
            "condition": condition,
            "condition_version": "2.0",
            "role_definition_name": "Role Based Access Control Administrator",
        },
    }
    prior = {
        "variables": {"workload": {"value": "example"}},
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "type": "synthetic",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": value,
                    "after_unknown": {},
                },
            }
            for address, value in values.items()
        ],
    }
    current = copy.deepcopy(prior)
    current.update(complete=True, errored=False, applyable=True)
    for entry in current["resource_changes"]:
        change = entry["change"]
        if entry["address"] == successor.APPLICATION:
            change.update(actions=["no-op"], before=copy.deepcopy(change["after"]))
        else:
            change["after"] = successor.repaired_values(entry["address"], change["after"])
    state = {
        "version": 4,
        "serial": 38,
        "lineage": "synthetic",
        "resources": [
            {
                "mode": "managed",
                "type": "azapi_resource",
                "name": "app_resource_group",
                "instances": [{"attributes": values[successor.APPLICATION]}],
            }
        ],
    }
    return prior, current, state


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "existing-delete",
        "existing-setting",
        "cache",
        "role",
        "extra-pending",
        "input",
        "import",
    ],
)
def test_successor_repairs_only_absent_vm_and_delegation(successor_plans, defect):
    import copy

    prior, current, state = successor_plans
    entries = current["resource_changes"]
    if defect == "existing-delete":
        entries[0]["change"]["actions"] = ["delete"]
    elif defect == "existing-setting":
        entries[0]["change"]["after"]["name"] = "changed"
    elif defect == "cache":
        entries[1]["change"]["after"]["os_disk"][0]["caching"] = "ReadWrite"
    elif defect == "role":
        entries[2]["change"]["after"]["condition"] += " OR true"
    elif defect == "extra-pending":
        entries.append(copy.deepcopy(entries[1]))
    elif defect == "input":
        current["variables"]["workload"]["value"] = "changed"
    elif defect == "import":
        entries[1]["change"]["importing"] = {"id": "foreign"}
    if defect:
        with pytest.raises(ValueError):
            successor.validate_successor_plan(current, prior, state)
    else:
        result = successor.validate_successor_plan(current, prior, state)
        assert result["preserved_managed_count"] == 1
        assert result["remaining_addresses"] == sorted([successor.VM, successor.DELEGATE])
        assert result["apply_authorized"] is False


@pytest.mark.parametrize("failure", [None, "apply", "plan", "approval", "late-plan"])
@pytest.mark.parametrize("successor_case", [False, True])
def test_recovery_execution_records_claim_before_effect_and_never_reapplies(
    tmp_path, monkeypatch, recovery_plans, successor_plans, failure, successor_case
):
    tmp_path.chmod(0o700)
    original_projection, projection, state = successor_plans if successor_case else recovery_plans
    original = tmp_path / "foundation/original"
    original.mkdir(parents=True, mode=0o700)
    original.parent.chmod(0o700)
    write_private_bytes(original.parent / "source-execution.lock", b"")
    work = tmp_path / "recovery"
    work.mkdir(mode=0o700)
    state_path = (
        original / "foundation-apply-bundle/source/infra/genesis-foundation/terraform.tfstate"
    )
    state_path.parent.mkdir(parents=True, mode=0o700)
    for parent in state_path.parents:
        if parent == tmp_path:
            break
        parent.chmod(0o700)
    write_private_bytes(state_path, canonical_bytes(state))
    target = SimpleNamespace(
        tenant_id="00000000-0000-0000-0000-000000000000",
        subscription_id="00000000-0000-0000-0000-000000000001",
    )
    target_binding = compute_target_binding(
        tenant_id=target.tenant_id, subscription_id=target.subscription_id
    )
    for values in (original_projection["variables"], projection["variables"]):
        values.update(
            {
                "tenant_id": {"value": target.tenant_id},
                "subscription_id": {"value": target.subscription_id},
            }
        )
    variables = {key: value["value"] for key, value in projection["variables"].items()}
    original_claim = {"claim": "original"}
    original_source = {"source_commit": "a" * 40}
    original_context = {
        "source_commit": "a" * 40,
        "terraform_digest": "b" * 64,
        "source_snapshot_digest": "c" * 64,
        "source_input_digest": canonical_digest(original_source),
    }
    prior = {
        "context": original_context,
        "plan_json_digest": hashlib.sha256(canonical_bytes(original_projection)).hexdigest(),
    }
    write_private_bytes(original / "foundation-plan.json", canonical_bytes(prior))
    write_private_bytes(work / "original-show.stdout", canonical_bytes(original_projection))
    write_private_bytes(work / "show.stdout", canonical_bytes(projection))
    write_private_bytes(work / "recovery.tfplan", b"saved-plan")
    write_private_bytes(work / "recovery-variables.json", canonical_bytes(variables))
    moment = datetime.now(UTC).replace(microsecond=0)
    evidence = {
        "schema_version": "fdai.foundation-recovery-review.v1",
        "state": "review",
        "source_commit": "a" * 40,
        "recovery_source_commit": "d" * 40,
        "original_review_digest": "e" * 64,
        "original_claim_digest": canonical_digest(original_claim),
        "original_state_digest": hashlib.sha256(canonical_bytes(state)).hexdigest(),
        "original_lineage_digest": canonical_digest({"lineage": state["lineage"]}),
        "target_binding": target_binding,
        "plan_digest": hashlib.sha256(b"saved-plan").hexdigest(),
        "plan_json_digest": hashlib.sha256(canonical_bytes(projection)).hexdigest(),
        "variables_digest": canonical_digest(variables),
        "configuration_digest": "f" * 64,
        "provider_digest": "f" * 64,
        "terraform_digest": "b" * 64,
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
        "original_state_unchanged": True,
        "application_group_absent": True,
        "created_at": moment.isoformat(),
        "expires_at": (moment + timedelta(hours=1)).isoformat(),
    }
    if successor_case:
        predecessor = tmp_path / "predecessor"
        predecessor.mkdir(mode=0o700)
        previous = {
            **evidence,
            "recovery_source_commit": "8" * 40,
            "plan_digest": hashlib.sha256(b"predecessor-plan").hexdigest(),
            "plan_json_digest": hashlib.sha256(canonical_bytes(original_projection)).hexdigest(),
        }
        previous["review_digest"] = canonical_digest(previous)
        previous_claim = {
            "schema_version": "fdai.foundation-recovery-claim.v1",
            "review_digest": previous["review_digest"],
            "plan_digest": previous["plan_digest"],
            "original_claim_digest": previous["original_claim_digest"],
            "original_state_digest": previous["original_state_digest"],
            "execution_source_commit": previous["recovery_source_commit"],
            "actor_digest": "1" * 64,
            "claimed_at": moment.isoformat(),
            "idempotency_key": canonical_digest(
                {
                    "review_digest": previous["review_digest"],
                    "original_state_digest": previous["original_state_digest"],
                }
            ),
        }
        for name, payload in (
            ("recovery-review.json", canonical_bytes(previous)),
            ("recovery-apply-claim.json", canonical_bytes(previous_claim)),
            ("show.stdout", canonical_bytes(original_projection)),
            ("recovery.tfplan", b"predecessor-plan"),
            ("recovery-variables.json", canonical_bytes(variables)),
        ):
            write_private_bytes(predecessor / name, payload)
        evidence.update(
            predecessor_directory=str(predecessor),
            predecessor_review_digest=previous["review_digest"],
            predecessor_claim_digest=canonical_digest(previous_claim),
            application_group_absent=False,
            application_group_preserved=True,
        )
        current_main = (ROOT / "infra/bootstrap/main.tf").read_bytes()
        old_main = current_main
        for before, after in successor.REPAIRS:
            old_main = old_main.replace(after, before)
        for path, payload in (
            (tmp_path / "snapshot/tree/infra/bootstrap/main.tf", old_main),
            (work / "source/infra/bootstrap/main.tf", current_main),
        ):
            path.parent.mkdir(parents=True, mode=0o700)
            path.write_bytes(payload)
    evidence["review_digest"] = canonical_digest(evidence)
    write_private_bytes(work / "recovery-review.json", canonical_bytes(evidence))
    approval = {
        "schema_version": "fdai.genesis-approval.v1",
        "run_binding": evidence["review_digest"],
        "source_commit": "d" * 40,
        "stage": "foundation-apply",
        "approved": True,
        "approved_at": moment.isoformat(),
        "expires_at": (moment + timedelta(minutes=30)).isoformat(),
        "actor_digest": "1" * 64,
        "evidence": {
            "plan_digest": evidence["plan_digest"],
            "review_digest": evidence["review_digest"],
        },
    }
    write_private_bytes(work / "approval.json", canonical_bytes(approval))
    calls = []
    monkeypatch.setattr(
        recovery,
        "inspect_source",
        lambda *_args, **_kwargs: SimpleNamespace(commit="d" * 40, reverify=lambda: None),
    )
    monkeypatch.setattr(
        recovery,
        "load_profile",
        lambda *_args: SimpleNamespace(
            environment="dev", transport="manual", target_binding=target_binding
        ),
    )
    monkeypatch.setattr(recovery, "verify_foundation_plan", lambda **_kwargs: {})
    monkeypatch.setattr(recovery, "load_apply_claim", lambda *_args, **_kwargs: original_claim)
    monkeypatch.setattr(
        recovery, "verify_source_snapshot", lambda *_args, **_kwargs: original_source
    )
    monkeypatch.setattr(recovery, "verify_execution_copy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "require_naming_only", lambda *_args: None)
    monkeypatch.setattr(recovery, "require_ip_policy_only", lambda *_args: None)
    monkeypatch.setattr(recovery, "active_azure_target", lambda: target)
    monkeypatch.setattr(recovery.image, "_trusted_terraform", lambda path: path)
    monkeypatch.setattr(recovery.image, "_trusted_azure_cli", lambda: Path("/synthetic/az"))
    monkeypatch.setattr(recovery.image, "_file_digest", lambda *_args: "b" * 64)
    monkeypatch.setattr(recovery.image, "_execution_tree_digest", lambda *_args: "f" * 64)
    monkeypatch.setattr(recovery.image, "_terraform_environment", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        recovery,
        "GenesisChecks",
        lambda *_args, **_kwargs: SimpleNamespace(
            verify_source=lambda **_kwargs: calls.append("ci")
        ),
    )
    monkeypatch.setattr(recovery, "current_actor_digest", lambda *_args: "1" * 64)
    monkeypatch.setattr(
        recovery,
        "recheck_foundation_vm",
        lambda **_kwargs: (
            (work / "recovery.tfplan").write_bytes(b"changed-after-preflight")
            if failure == "late-plan"
            else None
        ),
    )
    monkeypatch.setattr(recovery, "_validate_handoff", lambda *_args: None)
    monkeypatch.setattr(
        recovery, "_independent_readback", lambda *_args, **_kwargs: calls.append("observe")
    )
    monkeypatch.setattr(
        recovery.image,
        "_capture",
        lambda command, **_kwargs: (
            "false"
            if "exists" in command
            else "synthetic-group"
            if "group" in command and "show" in command
            else json.dumps(
                {
                    "source_commit": "a" * 40,
                    "private_reference": "synthetic",
                    "tenant_id": target.tenant_id,
                    "subscription_id": target.subscription_id,
                    "run_digest": "2" * 64,
                }
            )
        ),
    )

    def run(command, **kwargs):
        assert f"-state={state_path}" in command
        calls.append(kwargs["label"])
        if "apply" in command:
            assert (work / "recovery-apply-claim.json").exists()
            if failure == "apply":
                raise ValueError("simulated failed apply")
            state_path.write_bytes(canonical_bytes({**state, "serial": 28}))
        return b"ok"

    monkeypatch.setattr(recovery, "_run", run)
    arguments = dict(
        repository_root=ROOT,
        original_directory=original,
        source_snapshot=tmp_path / "snapshot",
        work_dir=work,
        terraform=tmp_path / "terraform",
        expected_review_digest=evidence["review_digest"],
        repository="example/project",
        approval_file=work / "approval.json",
    )
    if failure == "plan":
        (work / "recovery.tfplan").write_bytes(b"changed")
    elif failure == "approval":
        arguments["approval_file"] = None
    if failure is not None:
        with pytest.raises(ValueError):
            recovery.apply_recovery(**arguments)
        if failure != "apply":
            assert "apply" not in calls
            assert not (work / "recovery-apply-claim.json").exists()
            return
    else:
        result = recovery.apply_recovery(**arguments)
        assert result["control_plane_readback_verified"] is True
        assert result["zero_change_verified"] is True
        assert result["deployment_ready"] is False
        original_context["run_digest"] = "2" * 64
        (original / "foundation-plan.json").write_bytes(canonical_bytes(prior))
        monkeypatch.setattr(handover, "load_profile", recovery.load_profile)
        monkeypatch.setattr(handover, "verify_foundation_plan", recovery.verify_foundation_plan)
        monkeypatch.setattr(handover, "load_apply_claim", recovery.load_apply_claim)
        monkeypatch.setattr(handover, "verify_source_snapshot", recovery.verify_source_snapshot)
        with handover.recovery_lock(original):
            accepted = handover.load_recovery_handoff(
                original_directory=original,
                recovery_directory=work,
                source_snapshot=tmp_path / "snapshot",
                expected_digest=str(result["receipt_digest"]),
                target_binding=target_binding,
            )
        assert accepted.receipt == result
        assert accepted.foundation_reference["receipt_digest"] == result["receipt_digest"]
        assert "schema_version" not in accepted.foundation_reference
        assert not (original / "foundation-apply-receipt.json").exists()
        with (original.parent / "source-execution.lock").open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError), handover.recovery_lock(original):
                pytest.fail("a second handover must not acquire the original lock")
        receipt_path = work / "recovery-apply-receipt.json"
        for field, value in (
            ("zero_change_verified", False),
            ("runner_attested", True),
            ("execution_source_commit", "9" * 40),
            ("claim_digest", "0" * 64),
        ):
            altered = {**result, field: value}
            altered["receipt_digest"] = canonical_digest(
                {key: item for key, item in altered.items() if key != "receipt_digest"}
            )
            receipt_path.write_bytes(canonical_bytes(altered))
            with pytest.raises(ValueError):
                handover.load_recovery_handoff(
                    original_directory=original,
                    recovery_directory=work,
                    source_snapshot=tmp_path / "snapshot",
                    expected_digest=str(altered["receipt_digest"]),
                    target_binding=target_binding,
                )
        receipt_path.write_bytes(canonical_bytes(result))
        state_bytes = state_path.read_bytes()
        state_path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="current state differs"):
            handover.load_recovery_handoff(
                original_directory=original,
                recovery_directory=work,
                source_snapshot=tmp_path / "snapshot",
                expected_digest=str(result["receipt_digest"]),
                target_binding=target_binding,
            )
        state_path.write_bytes(state_bytes)
        assert calls.index("observe") < calls.index("zero-change")
        for _ in range(2):
            resumed = recovery.apply_recovery(
                **{**arguments, "approval_file": None, "verify_only": True}
            )
            assert resumed == result
    with pytest.raises(ValueError, match="never repeat"):
        recovery.apply_recovery(**arguments)
    assert calls.count("apply") == 1
    assert not (original / "foundation-apply-receipt.json").exists()


@pytest.fixture
def review():
    moment = datetime.now(UTC).replace(microsecond=0)
    return {
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "recovery_source_commit": "c" * 40,
        "original_claim_digest": "d" * 64,
        "original_state_digest": "e" * 64,
        "created_at": moment.isoformat(),
        "expires_at": (moment + timedelta(hours=1)).isoformat(),
    }


@pytest.mark.parametrize("defect", [None, "missing", "stage", "plan", "source", "actor", "expired"])
def test_exact_recovery_approval_requires_current_human_and_plan(
    tmp_path, monkeypatch, review, defect
):
    tmp_path.chmod(0o700)
    moment = datetime.now(UTC).replace(microsecond=0)
    approval = {
        "schema_version": "fdai.genesis-approval.v1",
        "run_binding": review["review_digest"],
        "source_commit": review["recovery_source_commit"],
        "stage": "foundation-apply",
        "approved": True,
        "approved_at": moment.isoformat(),
        "expires_at": (moment + timedelta(minutes=30)).isoformat(),
        "actor_digest": "f" * 64,
        "evidence": {
            "plan_digest": review["plan_digest"],
            "review_digest": review["review_digest"],
        },
    }
    if defect == "stage":
        approval["stage"] = "runner-image"
    elif defect == "plan":
        approval["evidence"]["plan_digest"] = "1" * 64
    elif defect == "source":
        approval["source_commit"] = "2" * 40
    elif defect == "actor":
        approval["actor_digest"] = "3" * 64
    elif defect == "expired":
        review["expires_at"] = (moment - timedelta(seconds=1)).isoformat()
    path = tmp_path / "approval.json"
    if defect != "missing":
        write_private_bytes(path, canonical_bytes(approval))
    monkeypatch.setattr(recovery, "current_actor_digest", lambda _binding: "f" * 64)
    if defect is None:
        assert recovery.require_current_approval(review, path) == "f" * 64
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            recovery.require_current_approval(review, None if defect == "missing" else path)


@pytest.mark.parametrize("defect", [None, "plan", "actor", "idempotency", "timestamp", "extra"])
def test_recovery_retained_claim_has_exact_identity_and_evidence(review, defect):
    claim = {
        "schema_version": "fdai.foundation-recovery-claim.v1",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "original_claim_digest": review["original_claim_digest"],
        "original_state_digest": review["original_state_digest"],
        "execution_source_commit": review["recovery_source_commit"],
        "idempotency_key": canonical_digest(
            {
                "review_digest": review["review_digest"],
                "original_state_digest": review["original_state_digest"],
            }
        ),
        "actor_digest": "f" * 64,
        "claimed_at": review["created_at"],
    }
    if defect == "plan":
        claim["plan_digest"] = "9" * 64
    elif defect == "actor":
        claim["actor_digest"] = "invalid"
    elif defect == "idempotency":
        claim["idempotency_key"] = "8" * 64
    elif defect == "timestamp":
        claim["claimed_at"] = review["expires_at"]
    elif defect == "extra":
        claim["extra"] = True
    if defect is None:
        recovery._validate_claim(claim, review)
    else:
        with pytest.raises(ValueError):
            recovery._validate_claim(claim, review)
