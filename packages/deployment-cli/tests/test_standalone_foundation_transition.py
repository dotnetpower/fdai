from __future__ import annotations

import json
import hashlib
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_foundation_transition as transition
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import write_private_bytes


def _write_tree(root: Path, *, marker: str) -> None:
    (root / "infra/genesis-foundation").mkdir(parents=True, mode=0o700)
    (root / "infra/genesis-foundation/.terraform.lock.hcl").write_text(
        "provider lock", encoding="utf-8"
    )
    (root / "infra/genesis-foundation/main.tf").write_text(marker, encoding="utf-8")
    (root / "infra/bootstrap").mkdir(mode=0o700)
    (root / "infra/bootstrap/bootstrap.sh").write_text("bootstrap", encoding="utf-8")
    (root / "infra/genesis-runner-image").mkdir(mode=0o700)
    (root / "infra/genesis-runner-image/toolchain.json").write_text(
        '{"terraform":"1.9.8"}', encoding="utf-8"
    )


def _kit(tmp_path: Path, *, marker: str = "same") -> SimpleNamespace:
    tmp_path.chmod(0o700)
    bundle = tmp_path / "bundle"
    _write_tree(bundle, marker=marker)
    kit_work = tmp_path / "kit-work"
    kit_work.mkdir(mode=0o700)
    kit_root = kit_work / "kit"
    kit_root.mkdir(mode=0o700)
    return SimpleNamespace(
        root=kit_root,
        bundle_root=bundle,
        source_commit="b" * 40,
        verification=SimpleNamespace(
            manifest_digest="1" * 64,
            terraform_binary="terraform",
            file_digests={"terraform": "2" * 64},
        ),
        runtime=SimpleNamespace(digest="3" * 64),
    )


def _review(
    directory: Path,
    *,
    expired: bool = False,
    summary: bool = False,
    delete: int = 0,
    replace: int = 0,
) -> dict[str, object]:
    directory.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.parent.chmod(0o700)
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    now = datetime.now(UTC).replace(microsecond=0)
    context = {
        "deployment_bundle_digest": "9" * 64,
        "foundation_context_digest": "8" * 64,
        "offline_manifest_digest": "7" * 64,
        "profile_digest": "6" * 64,
        "provider_lock_digest": transition._file_digest(
            directory.parents[1] / "bundle/infra/genesis-foundation/.terraform.lock.hcl"
        )
        if (directory.parents[1] / "bundle/infra/genesis-foundation/.terraform.lock.hcl").exists()
        else "5" * 64,
        "run_digest": "4" * 64,
        "runner_image_observation_digest": "3" * 64,
        "source_commit": "a" * 40,
        "target_binding": "2" * 64,
        "terraform_digest": "2" * 64,
        "variables_digest": "1" * 64,
    }
    value: dict[str, object] = {
        "schema_version": "fdai.foundation-saved-plan.v1",
        "state": "review",
        "apply_authorized": False,
        "source_eligibility_verified": False,
        "plan_origin_verified": False,
        "subscription_ready": False,
        "mutation_performed": False,
        "context": context,
        "plan_digest": "c" * 64,
        "plan_json_digest": "d" * 64,
        "terraform_version": "1.9.8",
        "created_at": (datetime(2000, 1, 1, tzinfo=UTC) if expired else now).isoformat(),
        "expires_at": (
            datetime(2000, 1, 1, 1, tzinfo=UTC) if expired else now + timedelta(hours=1)
        ).isoformat(),
    }
    if summary:
        counts = {
            "create": 1 if not delete and not replace else 0,
            "update": 0,
            "delete": delete,
            "replace": replace,
            "read": 0,
            "no-op": 8,
        }
        summary_value: dict[str, object] = {
            "schema_version": "fdai.foundation-plan-summary.v1",
            "action_counts": counts,
            "resource_type_counts": {"azurerm_role_assignment": sum(counts.values())},
            "resource_changes": [
                {
                    "address": "azurerm_role_assignment.bootstrap",
                    "actions": (
                        ["delete", "create"] if replace else ["delete"] if delete else ["create"]
                    ),
                }
            ],
        }
        summary_value["summary_digest"] = canonical_digest(summary_value)
        value["summary"] = summary_value
    value["review_digest"] = canonical_digest(value)
    write_private_bytes(directory / "foundation-plan.json", json.dumps(value).encode())
    return value


def _adoption(**_kwargs: object) -> dict[str, object]:
    return {
        "foundation_source_commit": "a" * 40,
        "application_source_commit": "b" * 40,
        "foundation_run_binding": "1" * 64,
        "adopted_run_binding": "2" * 64,
        "target_binding": "3" * 64,
        "receipt_digest": "4" * 64,
        "foundation_recovery_receipt_digest": "5" * 64,
        "foundation_enrollment_receipt_digest": "6" * 64,
        "foundation_state_receipt_digest": "7" * 64,
        "foundation_state_authority_digest": "8" * 64,
    }


def test_legacy_expired_review_with_unchanged_inputs_uses_pure_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path)
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True, summary=False)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: kit.bundle_root)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)

    receipt = transition.run_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=tmp_path / "run",
        retained_plan_ref="foundation-plan-attempt-2",
        transition_plan_ref=None,
        application_source_commit="b" * 40,
        kit_manifest_digest="1" * 64,
        runtime_release_digest="3" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
        transition_runner=lambda **_kwargs: pytest.fail("unchanged inputs must not plan"),
    )

    assert receipt["receipt_digest"] == "4" * 64
    assert not (tmp_path / "run/foundation-lineage-transition-receipt.json").exists()


def test_changed_inputs_run_transition_plan_with_newer_root_and_bind_zero_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path, marker='principal_type = "ServicePrincipal"')
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True, summary=False)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)
    invoked: dict[str, object] = {}
    calls: list[str] = []

    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs["operation"]))
        decision = kwargs["decision"]
        assert isinstance(decision, transition.TransitionDecision)
        invoked["current_root"] = decision.current_inputs["terraform_root_digest"]
        invoked["retained_root"] = decision.retained_inputs["terraform_root_digest"]
        summary = _summary()
        if kwargs["operation"] == "plan":
            return {
                "archive_digest": "a" * 64,
                "helper_digest": "b" * 64,
                "review_digest": "9" * 64,
                "remote_state_digest": "e" * 64,
                "plan_digest": "c" * 64,
                "plan_json_digest": "d" * 64,
                "summary": summary,
                "zero_change_verified": True,
            }
        return {
            "receipt_digest": "0" * 64,
            "zero_change_verified": True,
            "mutation_performed": False,
            "remote_state_digest": "e" * 64,
            "plan_json_digest": "f" * 64,
        }

    receipt = transition.run_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=tmp_path / "run",
        retained_plan_ref="foundation-plan-attempt-2",
        transition_plan_ref=None,
        application_source_commit="b" * 40,
        kit_manifest_digest="1" * 64,
        runtime_release_digest="3" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
        transition_runner=runner,
    )

    assert invoked["current_root"] != invoked["retained_root"]
    assert calls == ["plan", "verify"]
    assert receipt["receipt_digest"] == "4" * 64
    transition_receipt = json.loads(
        (tmp_path / "run/foundation-lineage-transition-receipt.json").read_text()
    )
    assert transition_receipt["schema_version"] == "fdai.foundation-lineage-transition.v2"
    assert transition_receipt["zero_change_verified"] is True
    assert transition_receipt["mutation_performed"] is False


def test_zero_change_verified_comes_from_remote_plan_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path, marker="changed")
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)

    def runner(**kwargs: object) -> dict[str, object]:
        if kwargs["operation"] == "plan":
            return {
                "archive_digest": "a" * 64,
                "helper_digest": "b" * 64,
                "review_digest": "9" * 64,
                "remote_state_digest": "e" * 64,
                "plan_digest": "c" * 64,
                "plan_json_digest": "d" * 64,
                "summary": _summary(),
                "zero_change_verified": False,
            }
        return {
            "receipt_digest": "0" * 64,
            "zero_change_verified": False,
            "mutation_performed": True,
            "remote_state_digest": "e" * 64,
            "plan_json_digest": "f" * 64,
        }

    receipt = transition.run_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=tmp_path / "run",
        retained_plan_ref="foundation-plan-attempt-2",
        transition_plan_ref=None,
        application_source_commit="b" * 40,
        kit_manifest_digest="1" * 64,
        runtime_release_digest="3" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
        transition_runner=runner,
    )

    transition_receipt = json.loads(
        (tmp_path / "run/foundation-lineage-transition-receipt.json").read_text()
    )
    assert receipt["receipt_digest"] == "4" * 64
    assert transition_receipt["zero_change_verified"] is False
    assert transition_receipt["mutation_performed"] is True


def test_destructive_transition_refuses_without_tty_confirmation(
    tmp_path: Path,
) -> None:
    _review(tmp_path / "foundation-plan-attempt-3", summary=True, delete=1)

    with pytest.raises(ValueError, match="interactive terminal"):
        transition.approve_transition_plan(tmp_path / "foundation-plan-attempt-3")


def test_destructive_transition_accepts_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _review(tmp_path / "foundation-plan-attempt-3", summary=True, replace=1)
    monkeypatch.setattr(
        transition,
        "_approval_input",
        lambda **_kwargs: "foundation-transition-apply-destructive",
    )

    transition.approve_transition_plan(tmp_path / "foundation-plan-attempt-3")


def test_destructive_transition_does_not_apply_before_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path, marker="changed")
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    calls: list[str] = []

    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs["operation"]))
        if kwargs["operation"] != "plan":
            pytest.fail("apply must not run before destructive confirmation")
        return {
            "archive_digest": "a" * 64,
            "helper_digest": "b" * 64,
            "review_digest": "9" * 64,
            "remote_state_digest": "e" * 64,
            "plan_digest": "c" * 64,
            "plan_json_digest": "d" * 64,
            "summary": _summary(delete=1),
            "zero_change_verified": False,
        }

    with pytest.raises(ValueError, match="interactive terminal"):
        transition.run_foundation_transition(
            kit=kit,  # type: ignore[arg-type]
            run_root=tmp_path / "run",
            retained_plan_ref="foundation-plan-attempt-2",
            transition_plan_ref=None,
            application_source_commit="b" * 40,
            kit_manifest_digest="1" * 64,
            runtime_release_digest="3" * 64,
            tenant_id="00000000-0000-0000-0000-000000000001",
            subscription_id="00000000-0000-0000-0000-000000000002",
            region="westus3",
            monthly_cost_ceiling=1000,
            transition_runner=runner,
        )

    assert calls == ["plan"]


def test_unverifiable_retained_baseline_stops_before_transition(tmp_path: Path) -> None:
    kit = _kit(tmp_path, marker="changed")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)

    with pytest.raises(ValueError, match="foundation_transition_baseline_unverifiable"):
        transition.decide_foundation_transition(
            kit=kit,  # type: ignore[arg-type]
            run_root=tmp_path / "run",
            retained_plan_ref="foundation-plan-attempt-2",
        )


def test_current_digest_computation_matches_foundation_plan_context(
    tmp_path: Path,
) -> None:
    kit = _kit(tmp_path)
    review = _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)

    digests = transition._current_input_digests(kit, review)  # noqa: SLF001

    assert (
        digests["provider_lock_digest"]
        == hashlib.sha256(
            (kit.bundle_root / "infra/genesis-foundation/.terraform.lock.hcl").read_bytes()
        ).hexdigest()
    )
    assert (
        digests["terraform_digest"]
        == dict(kit.verification.file_digests)[kit.verification.terraform_binary]
    )


def test_default_runner_zero_change_writes_receipt_then_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path, marker="changed")
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)
    _status(tmp_path / "run")
    selected = tmp_path / "run" / "foundation-variables-with-image.json"
    monkeypatch.setattr(transition, "retained_variables_file", lambda _run, _plan: selected)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)
    calls: list[str] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[command.index("--variables-file") + 1] == str(selected)
        calls.append(command[2])
        if command[2] == "plan":
            return subprocess.CompletedProcess(
                command, 0, json.dumps(_transport_plan(zero=True)), ""
            )
        if command[2] == "verify":
            return subprocess.CompletedProcess(command, 0, json.dumps(_transport_apply(False)), "")
        raise AssertionError(command)

    monkeypatch.setattr(transition.subprocess, "run", run)

    for _ in range(2):
        transition.run_foundation_transition(
            kit=kit,  # type: ignore[arg-type]
            run_root=tmp_path / "run",
            retained_plan_ref="foundation-plan-attempt-2",
            transition_plan_ref=None,
            application_source_commit="b" * 40,
            kit_manifest_digest="1" * 64,
            runtime_release_digest="3" * 64,
            tenant_id="00000000-0000-0000-0000-000000000001",
            subscription_id="00000000-0000-0000-0000-000000000002",
            region="westus3",
            monthly_cost_ceiling=1000,
        )

    assert calls == ["plan", "verify"]


def test_default_runner_applies_with_transport_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path, marker="changed")
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)
    _status(tmp_path / "run")
    selected = tmp_path / "run" / "foundation-variables-with-image.json"
    monkeypatch.setattr(transition, "retained_variables_file", lambda _run, _plan: selected)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)
    observed: dict[str, str] = {}

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[command.index("--variables-file") + 1] == str(selected)
        if command[2] == "plan":
            return subprocess.CompletedProcess(
                command, 0, json.dumps(_transport_plan(zero=False)), ""
            )
        if command[2] == "apply":
            observed["review"] = command[command.index("--expected-review-digest") + 1]
            observed["plan"] = command[command.index("--expected-plan-digest") + 1]
            return subprocess.CompletedProcess(command, 0, json.dumps(_transport_apply(True)), "")
        raise AssertionError(command)

    monkeypatch.setattr(transition.subprocess, "run", run)

    transition.run_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=tmp_path / "run",
        retained_plan_ref="foundation-plan-attempt-2",
        transition_plan_ref=None,
        application_source_commit="b" * 40,
        kit_manifest_digest="1" * 64,
        runtime_release_digest="3" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
    )

    assert observed == {"review": "9" * 64, "plan": "c" * 64}


def test_claim_resume_uses_verify_without_replan_or_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = _kit(tmp_path, marker="changed")
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)
    _status(tmp_path / "run")
    selected = tmp_path / "run" / "foundation-variables-with-image.json"
    monkeypatch.setattr(transition, "retained_variables_file", lambda _run, _plan: selected)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)
    attempt = tmp_path / "run/foundation-transition-attempt-1"
    attempt.mkdir(mode=0o700)
    transition._write_transition_review(  # noqa: SLF001
        attempt, _transport_plan(zero=False), _current_inputs(kit, tmp_path / "run")
    )
    write_private_bytes(attempt / "foundation-transition-claim.json", b"{}\n")
    calls: list[str] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[command.index("--variables-file") + 1] == str(selected)
        calls.append(command[2])
        if command[2] == "verify":
            return subprocess.CompletedProcess(command, 0, json.dumps(_transport_apply(False)), "")
        raise AssertionError(command)

    monkeypatch.setattr(transition.subprocess, "run", run)

    transition.run_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=tmp_path / "run",
        retained_plan_ref="foundation-plan-attempt-2",
        transition_plan_ref=None,
        application_source_commit="b" * 40,
        kit_manifest_digest="1" * 64,
        runtime_release_digest="3" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
    )

    assert calls == ["verify"]


def _summary(delete: int = 0, replace: int = 0) -> dict[str, object]:
    counts = {
        "create": 1 if not delete and not replace else 0,
        "update": 0,
        "delete": delete,
        "replace": replace,
        "read": 0,
        "no-op": 8,
    }
    summary: dict[str, object] = {
        "schema_version": "fdai.foundation-transition-plan-summary.v1",
        "action_counts": counts,
        "resource_changes": [
            {
                "address": "azurerm_role_assignment.bootstrap",
                "actions": ["delete", "create"]
                if replace
                else ["delete"]
                if delete
                else ["create"],
            }
        ],
    }
    summary["summary_digest"] = canonical_digest(summary)
    return summary


def _transport_plan(*, zero: bool) -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-foundation-transition-plan.v1",
        "state": "review",
        "review_digest": "9" * 64,
        "archive_digest": "a" * 64,
        "helper_digest": "b" * 64,
        "remote_state_digest": "e" * 64,
        "plan_digest": "c" * 64,
        "plan_json_digest": "d" * 64,
        "summary": _summary(),
        "zero_change_verified": zero,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _transport_apply(mutation: bool) -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-foundation-transition-apply.v1",
        "state": "verified",
        "receipt_digest": "0" * 64,
        "zero_change_verified": True,
        "mutation_performed": mutation,
        "remote_state_digest": "e" * 64,
        "plan_digest": "c" * 64,
        "plan_json_digest": "f" * 64,
        "subscription_ready": False,
    }


def _status(root: Path) -> None:
    write_private_bytes(
        root / "status.json",
        json.dumps(
            {
                "foundation_report": {
                    "foundation_apply": {"receipt_digest": "5" * 64},
                    "runner_enrollment": {"receipt_digest": "6" * 64},
                }
            }
        ).encode(),
    )


_VARIABLE_TENANT = "00000000-0000-0000-0000-000000000000"
_VARIABLE_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


def _variable_values(binding: str) -> dict[str, object]:
    return {
        "tenant_id": _VARIABLE_TENANT,
        "subscription_id": _VARIABLE_SUBSCRIPTION,
        "target_binding": binding,
        "region": "koreacentral",
        "workload": "example",
        "region_short": "krc",
        "state_storage_account_name": "examplestate",
        "ops_address_space": "10.40.0.0/16",
        "runner_subnet_prefix": "10.40.1.0/24",
        "pe_subnet_prefix": "10.40.2.0/24",
        "runner_ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA==",
        "runner_source_image_id": (
            f"/subscriptions/{_VARIABLE_SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.Compute/images/example"
        ),
        "runner_bootstrap_mode": "offline",
        "runner_marketplace_image_version": "",
        "source_commit": "a" * 40,
        "run_digest": "b" * 64,
        "foundation_context_digest": "c" * 64,
        "runner_image_toolchain_digest": "d" * 64,
    }


def _variables_run(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    from fdai_deployment_cli.contracts import ProvisionProfile
    from fdai_deployment_cli.foundation_input import snapshot_foundation_input
    from fdai_deployment_cli.plan_input import read_plan_input
    from fdai_deployment_cli.profile import write_profile
    from fdai_deployment_cli.target import compute_target_binding

    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    binding = compute_target_binding(
        tenant_id=_VARIABLE_TENANT, subscription_id=_VARIABLE_SUBSCRIPTION
    )
    write_profile(
        run / "profile.json",
        ProvisionProfile(
            environment="dev",
            region="koreacentral",
            target_binding=binding,
            connectivity="offline",
            host="managed-vm",
            transport="manual",
            access_method="bastion",
            shadow_only=True,
            approval_quorum=1,
            monthly_cost_ceiling=500,
        ),
    )
    reviewed = _variable_values(binding)
    plain = {**reviewed, "runner_source_image_id": reviewed["runner_source_image_id"] + "-plain"}
    for name, values in (
        ("foundation-variables-with-image.json", reviewed),
        ("foundation-variables.json", plain),
    ):
        (run / name).write_text(json.dumps(values), encoding="utf-8")
        (run / name).chmod(0o600)
    snapshot = tmp_path / "reviewed-snapshot.json"
    snapshot_foundation_input(
        run / "foundation-variables-with-image.json",
        snapshot,
        expected_target_binding=binding,
        expected_region="koreacentral",
        expected_environment="dev",
    )
    plan = run / "foundation-plan-attempt-2"
    _review(plan, expired=True)
    review = json.loads((plan / "foundation-plan.json").read_text(encoding="utf-8"))
    review["context"]["variables_digest"] = canonical_digest(read_plan_input(snapshot))
    review.pop("review_digest")
    review["review_digest"] = canonical_digest(review)
    (plan / "foundation-plan.json").write_text(json.dumps(review), encoding="utf-8")
    return run, plan, review


def test_retained_variables_file_is_selected_by_the_reviewed_digest(tmp_path: Path) -> None:
    run, plan, _review_value = _variables_run(tmp_path)

    selected = transition.retained_variables_file(run, plan)

    assert selected == run / "foundation-variables-with-image.json"


def test_retained_variables_file_fails_closed_without_a_reviewed_match(tmp_path: Path) -> None:
    run, plan, _review_value = _variables_run(tmp_path)
    (run / "foundation-variables-with-image.json").unlink()

    with pytest.raises(ValueError, match="foundation_transition_variables_unverifiable"):
        transition.retained_variables_file(run, plan)


def _current_inputs(kit: SimpleNamespace, run_root: Path) -> dict[str, str]:
    return transition.decide_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=run_root,
        retained_plan_ref="foundation-plan-attempt-2",
    ).current_inputs


def _other_inputs(current: dict[str, str]) -> dict[str, str]:
    return {
        key: ("f" * 64 if key == "terraform_root_digest" else value)
        for key, value in current.items()
    }


def _prepared_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, Path]:
    kit = _kit(tmp_path, marker="changed")
    old_bundle = tmp_path / "old-bundle"
    _write_tree(old_bundle, marker="")
    _review(tmp_path / "run/foundation-plan-attempt-2", expired=True)
    _status(tmp_path / "run")
    selected = tmp_path / "run" / "foundation-variables-with-image.json"
    monkeypatch.setattr(transition, "retained_variables_file", lambda _run, _plan: selected)
    monkeypatch.setattr(transition, "_retained_bundle_root", lambda *_args: old_bundle)
    monkeypatch.setattr(transition, "_find_digest", lambda _root, expected: expected)
    monkeypatch.setattr(transition, "write_lineage_adoption_receipt", _adoption)
    return kit, tmp_path / "run"


def _run_transition(
    kit: SimpleNamespace, run_root: Path, *, transition_plan_ref: str | None = None
) -> dict[str, object]:
    return transition.run_foundation_transition(
        kit=kit,  # type: ignore[arg-type]
        run_root=run_root,
        retained_plan_ref="foundation-plan-attempt-2",
        transition_plan_ref=transition_plan_ref,
        application_source_commit="b" * 40,
        kit_manifest_digest="1" * 64,
        runtime_release_digest="3" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
    )


def test_completed_attempt_for_other_inputs_is_superseded_by_a_new_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit, run_root = _prepared_run(tmp_path, monkeypatch)
    older = run_root / "foundation-transition-attempt-1"
    older.mkdir(mode=0o700)
    transition._write_transition_review(  # noqa: SLF001
        older, _transport_plan(zero=True), _other_inputs(_current_inputs(kit, run_root))
    )
    write_private_bytes(older / "foundation-transition-remote-receipt.json", b"{}\n")
    calls: list[tuple[str, str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        attempt = Path(command[command.index("--transition-directory") + 1]).name
        calls.append((command[2], attempt))
        if command[2] == "plan":
            return subprocess.CompletedProcess(
                command, 0, json.dumps(_transport_plan(zero=True)), ""
            )
        if command[2] == "verify":
            return subprocess.CompletedProcess(command, 0, json.dumps(_transport_apply(False)), "")
        raise AssertionError(command)

    monkeypatch.setattr(transition.subprocess, "run", run)

    _run_transition(kit, run_root)

    assert calls == [
        ("plan", "foundation-transition-attempt-2"),
        ("verify", "foundation-transition-attempt-2"),
    ]


def test_interrupted_apply_for_other_inputs_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit, run_root = _prepared_run(tmp_path, monkeypatch)
    older = run_root / "foundation-transition-attempt-1"
    older.mkdir(mode=0o700)
    transition._write_transition_review(  # noqa: SLF001
        older, _transport_plan(zero=False), _other_inputs(_current_inputs(kit, run_root))
    )
    write_private_bytes(older / "foundation-transition-claim.json", b"{}\n")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(command)

    monkeypatch.setattr(transition.subprocess, "run", run)

    with pytest.raises(ValueError, match="foundation_transition_interrupted_for_other_inputs"):
        _run_transition(kit, run_root)


def test_explicit_attempt_for_other_inputs_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit, run_root = _prepared_run(tmp_path, monkeypatch)
    older = run_root / "foundation-transition-attempt-1"
    older.mkdir(mode=0o700)
    transition._write_transition_review(  # noqa: SLF001
        older, _transport_plan(zero=True), _other_inputs(_current_inputs(kit, run_root))
    )
    write_private_bytes(older / "foundation-transition-remote-receipt.json", b"{}\n")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(command)

    monkeypatch.setattr(transition.subprocess, "run", run)

    with pytest.raises(ValueError, match="foundation_transition_attempt_inputs_differ"):
        _run_transition(kit, run_root, transition_plan_ref="foundation-transition-attempt-1")


def test_runner_failure_carries_the_bounded_transport_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit, run_root = _prepared_run(tmp_path, monkeypatch)
    guid = "00000000-0000-0000-0000-000000000009"

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        reason = f"Foundation transition remote operation failed: lookup failed for {guid}"
        return subprocess.CompletedProcess(
            command, 3, json.dumps({"state": "failed", "reason": reason}), ""
        )

    monkeypatch.setattr(transition.subprocess, "run", run)

    with pytest.raises(ValueError) as caught:
        _run_transition(kit, run_root)

    assert str(caught.value) == (
        "Foundation transition remote operation failed: lookup failed for redacted-id"
    )


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("not json", "Foundation transition remote operation failed"),
        (
            json.dumps({"reason": 'token="secret"'}),
            "Foundation transition remote operation failed",
        ),
        (
            json.dumps({"reason": "runner SSH private key does not match the Foundation handoff"}),
            "Foundation transition remote operation failed: "
            "runner SSH private key does not match the Foundation handoff",
        ),
    ],
)
def test_runner_failure_reason_is_bounded(stdout: str, expected: str) -> None:
    assert transition._runner_failure(stdout) == expected  # noqa: SLF001
