"""Adversarial tests for claim-first bounded Entra convergence."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.entra_profiles import EntraControlProfile, EntraTargetProfile
from fdai_deployment_cli.identity_profile import (
    IdentityProfileEvidence,
    IdentityProfileObservation,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_entra_operation  # noqa: E402

HUMAN = "00000000-0000-0000-0000-000000000003"
EXECUTOR = "00000000-0000-0000-0000-000000000004"
EXECUTOR_CLIENT = "00000000-0000-0000-0000-000000000005"
APPS = ("fdai-api", "fdai-approval-bot", "fdai-console-spa")
ROLE_GROUPS = {
    "readers": "00000000-0000-0000-0000-000000000011",
    "contributors": "00000000-0000-0000-0000-000000000012",
    "approvers": "00000000-0000-0000-0000-000000000013",
    "owners": "00000000-0000-0000-0000-000000000014",
    "break_glass": "00000000-0000-0000-0000-000000000015",
}
SNAPSHOT_DIGEST = "9" * 64
SOURCE_COMMIT = "a" * 40


class ApprovalInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def _profiles(*, environment: str = "dev") -> tuple[EntraTargetProfile, EntraControlProfile]:
    controls = EntraControlProfile.from_mapping(
        {
            "schema_version": "fdai.entra-control-profile.v1",
            "premium_service_plan": "AAD_PREMIUM_P2",
            "role_groups": ROLE_GROUPS,
            "conditional_access_policies": [
                {
                    "policy_id": "00000000-0000-0000-0000-000000000021",
                    "include_group_slots": ["approvers", "owners"],
                    "exclude_group_slots": [],
                    "include_users": [],
                    "exclude_users": [],
                    "include_roles": [],
                    "exclude_roles": [],
                    "client_app_types": ["all"],
                    "include_applications": ["All"],
                    "exclude_applications": [],
                    "include_platforms": [],
                    "exclude_platforms": [],
                    "include_locations": [],
                    "exclude_locations": [],
                    "sign_in_risk_levels": [],
                    "user_risk_levels": [],
                    "device_filter_mode": None,
                    "device_filter_rule": None,
                    "grant_operator": "AND",
                    "grant_controls": ["authenticationStrength"],
                    "authentication_strength_id": "00000000-0000-0000-0000-000000000022",
                }
            ],
            "access_reviews": [
                {
                    "definition_id": "00000000-0000-0000-0000-000000000031",
                    "group_slot": "owners",
                    "scope_query_type": "MicrosoftGraph",
                    "recurrence_pattern_type": "absoluteMonthly",
                    "recurrence_interval": 1,
                    "recurrence_range_type": "noEnd",
                    "duration_days": 14,
                    "allowed_statuses": ["NotStarted"],
                }
            ],
            "authentication_methods": [
                {
                    "method_id": "fido2",
                    "state": "enabled",
                    "include_group_slots": ["approvers", "owners"],
                }
            ],
            "azure_policy_assignments": [
                {
                    "assignment_id": "/subscriptions/example/providers/policyAssignments/fdai",
                    "definition_id": "/providers/policyDefinitions/fdai-deny",
                    "enforcement_mode": "Default",
                    "scope": "/subscriptions/example",
                }
            ],
        }
    )
    target = EntraTargetProfile.from_mapping(
        {
            "schema_version": "fdai.entra-target-profile.v2",
            "environment": environment,
            "target_binding": "b" * 64,
            "executor_object_id": EXECUTOR,
            "executor_client_id": EXECUTOR_CLIENT,
            "executor_display_name": "id-fdai-dev-executor",
            "executor_azure_config_dir": "/opt/fdai/private/executor-azure",
            "control_profile_digest": controls.digest,
        }
    )
    return target, controls


def _observation(*, premium: bool = True) -> IdentityProfileObservation:
    return IdentityProfileObservation.from_evidence(
        IdentityProfileEvidence(
            premium_license_eligible=premium,
            role_groups_present=True,
            role_group_profile_match=True,
            conditional_access_policy_present=True,
            access_review_present=True,
            authentication_method_policy_present=True,
            phishing_resistant_method_enabled=True,
            azure_policy_assignment_present=True,
            human_identity_present=True,
            human_approver_authorized=True,
            executor_identity_present=True,
            executor_is_managed_identity=True,
            executor_profile_match=True,
            human_executor_separated=True,
        )
    )


def _plan(*, complete: bool = False):
    body = {
        "schema_version": "fdai.genesis-entra-plan.v1",
        "create_apps": [] if complete else list(APPS),
        "create_groups": [],
        "require_existing_role_groups": True,
        "role_group_binding_digest": canonical_digest({"role_groups": ROLE_GROUPS}),
        "configure_api_roles_and_scope": True,
        "configure_runner_owned_spa_graph_permission": False,
        "provider_admin_consent": False,
    }
    return genesis_entra_operation.EntraPlan(
        create_apps=() if complete else APPS,
        create_groups=(),
        configure_roles=True,
        configure_runner_graph=False,
        digest=canonical_digest(body),
        role_groups=tuple(sorted(ROLE_GROUPS.items())),
    )


def _readback():
    return genesis_entra_operation.EntraEffectReadback(
        bindings={"OPERATOR_API_AUDIENCE": "api://private"},
        evidence_digest="8" * 64,
    )


def _ready_runtime(tmp_path: Path, monkeypatch, *, environment: str = "dev"):
    target, controls = _profiles(environment=environment)
    work_dir = tmp_path / "identity"
    work_dir.mkdir(mode=0o700)
    snapshot = tmp_path / "snapshot"
    monkeypatch.setattr(
        genesis_entra_operation,
        "verify_source_snapshot",
        lambda *_args, **_kwargs: {"source_commit": SOURCE_COMMIT},
    )
    monkeypatch.setattr(
        genesis_entra_operation, "azure_active_target_binding", lambda: target.target_binding
    )
    monkeypatch.setattr(
        genesis_entra_operation,
        "observe_identity_profile",
        lambda *_args: (_observation(), HUMAN),
    )
    monkeypatch.setattr(genesis_entra_operation, "current_actor_digest", lambda _binding: "e" * 64)
    execution_digest = hashlib.sha256(EXECUTOR.casefold().encode()).hexdigest()
    monkeypatch.setattr(
        genesis_entra_operation,
        "executor_execution_context",
        lambda _target: nullcontext(execution_digest),
    )
    return target, controls, work_dir, snapshot


def _approve(monkeypatch) -> None:
    original = genesis_entra_operation.create_approval
    monkeypatch.setattr(
        genesis_entra_operation,
        "create_approval",
        lambda **kwargs: original(
            **kwargs,
            input_stream=ApprovalInput("entra-config\n"),
            output_stream=io.StringIO(),
            now=datetime.now(UTC),
        ),
    )


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_non_dev_apply_stops_before_snapshot_provider_or_workdir(
    tmp_path, monkeypatch, environment
) -> None:
    target, controls = _profiles(environment=environment)
    work_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        genesis_entra_operation,
        "verify_source_snapshot",
        lambda *_args, **_kwargs: pytest.fail("non-dev apply reached snapshot read"),
    )
    monkeypatch.setattr(
        genesis_entra_operation,
        "azure_active_target_binding",
        lambda: pytest.fail("non-dev apply reached provider target read"),
    )

    with pytest.raises(ValueError, match="profile-bound dev"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=tmp_path / "snapshot",
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )
    assert not work_dir.exists()


def test_failed_profile_preflight_has_no_approval_claim_or_mutation(tmp_path, monkeypatch) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    monkeypatch.setattr(
        genesis_entra_operation,
        "observe_identity_profile",
        lambda *_args: (_observation(premium=False), HUMAN),
    )
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    monkeypatch.setattr(
        genesis_entra_operation,
        "apply_entra_bounded",
        lambda *_args, **_kwargs: pytest.fail("failed preflight reached mutation"),
    )

    result = genesis_entra_operation.run_entra_operation(
        work_dir=work_dir,
        target=target,
        controls=controls,
        snapshot_directory=snapshot,
        snapshot_digest=SNAPSHOT_DIGEST,
        apply=True,
    )

    assert result["state"] == "blocked"
    assert result["mutation_performed"] is False
    assert not (work_dir / "entra-only-claim.json").exists()


def test_full_success_binds_snapshot_claim_and_complete_effect_receipt(
    tmp_path, monkeypatch
) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    _approve(monkeypatch)
    calls: list[str] = []

    def apply(_plan):
        calls.append("apply")
        claim = json.loads((work_dir / "entra-only-claim.json").read_text())
        assert claim["snapshot_digest"] == SNAPSHOT_DIGEST
        assert claim["target_profile_digest"] == target.digest
        assert claim["control_profile_digest"] == controls.digest
        assert claim["plan"]["create_groups"] == []
        assert claim["plan"]["require_existing_role_groups"] is True
        assert claim["approval_principal_digest"] != claim["execution_actor_digest"]
        assert claim["execution_actor_digest"] == claim["executor_digest"]

    monkeypatch.setattr(genesis_entra_operation, "apply_entra_bounded", apply)
    monkeypatch.setattr(
        genesis_entra_operation,
        "read_entra_effects",
        lambda **_kwargs: calls.append("readback") or _readback(),
    )

    result = genesis_entra_operation.run_entra_operation(
        work_dir=work_dir,
        target=target,
        controls=controls,
        snapshot_directory=snapshot,
        snapshot_digest=SNAPSHOT_DIGEST,
        apply=True,
    )

    assert calls == ["apply", "readback"]
    assert result["state"] == "applied"
    assert result["plan"]["create_groups"] == []
    assert result["plan"]["require_existing_role_groups"] is True
    assert result["plan"]["role_group_binding_digest"] == canonical_digest(
        {"role_groups": ROLE_GROUPS}
    )
    assert result["effects"] == _readback().projection()
    assert result["runner_directory_authority_granted"] is False
    rendered = json.dumps(result, sort_keys=True)
    assert EXECUTOR not in rendered
    assert EXECUTOR_CLIENT not in rendered
    assert all(group_id not in rendered for group_id in ROLE_GROUPS.values())
    receipt_path = work_dir / "entra-only-receipt.json"
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    receipt = json.loads(receipt_path.read_text())
    assert HUMAN not in json.dumps(receipt)
    assert receipt["snapshot_digest"] == SNAPSHOT_DIGEST
    assert receipt["effects"]["group_role_assignments_verified"] is True
    assert receipt["effects"]["owner_membership_changed_by_operation"] is False
    assert receipt["effects"]["runner_spa_ownership_granted_by_operation"] is False
    assert receipt["effects"]["graph_application_readwrite_ownedby_granted_by_operation"] is False
    assert receipt["approval_executor_separated"] is True
    assert receipt["approval_principal_digest"] != receipt["execution_actor_digest"]


@pytest.mark.parametrize(
    "effect",
    [
        "applications",
        "service_principals",
        "role_scope_definitions",
        "group_role_assignments",
    ],
)
def test_crash_before_each_effect_never_yields_applied_receipt(
    tmp_path, monkeypatch, effect
) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    _approve(monkeypatch)
    apply_count = 0

    def crash(_plan):
        nonlocal apply_count
        apply_count += 1
        raise RuntimeError(f"crash-before-{effect}")

    monkeypatch.setattr(genesis_entra_operation, "apply_entra_bounded", crash)

    with pytest.raises(RuntimeError, match=effect):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )
    assert (work_dir / "entra-only-claim.json").exists()
    assert not (work_dir / "entra-only-receipt.json").exists()

    monkeypatch.setattr(
        genesis_entra_operation,
        "apply_entra_bounded",
        lambda *_args, **_kwargs: pytest.fail("claim recovery repeated apply"),
    )
    monkeypatch.setattr(
        genesis_entra_operation,
        "read_entra_effects",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(f"partial-{effect}-readback")),
    )
    with pytest.raises(ValueError, match="automatic retry is blocked"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )
    assert apply_count == 1
    assert not (work_dir / "entra-only-receipt.json").exists()


def test_changed_active_target_after_approval_never_writes_claim(tmp_path, monkeypatch) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    bindings = iter((target.target_binding, "f" * 64))
    monkeypatch.setattr(
        genesis_entra_operation, "azure_active_target_binding", lambda: next(bindings)
    )
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    _approve(monkeypatch)

    with pytest.raises(ValueError, match="target changed"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )
    assert not (work_dir / "entra-only-claim.json").exists()


def test_wrong_authenticated_executor_never_writes_claim(tmp_path, monkeypatch) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    monkeypatch.setattr(
        genesis_entra_operation,
        "executor_execution_context",
        lambda _target: nullcontext("f" * 64),
    )
    monkeypatch.setattr(
        genesis_entra_operation,
        "apply_entra_bounded",
        lambda *_args, **_kwargs: pytest.fail("wrong executor reached mutation"),
    )
    _approve(monkeypatch)

    with pytest.raises(ValueError, match="executor does not match"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )

    assert not (work_dir / "entra-only-claim.json").exists()


def test_claim_recovery_requires_complete_readback_and_never_reapplies(
    tmp_path, monkeypatch
) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    _approve(monkeypatch)
    apply_count = 0

    def ambiguous(_plan):
        nonlocal apply_count
        apply_count += 1
        raise RuntimeError("ambiguous-after-effects")

    monkeypatch.setattr(genesis_entra_operation, "apply_entra_bounded", ambiguous)
    with pytest.raises(RuntimeError, match="ambiguous"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )

    monkeypatch.setattr(
        genesis_entra_operation,
        "apply_entra_bounded",
        lambda *_args, **_kwargs: pytest.fail("claim recovery repeated apply"),
    )
    monkeypatch.setattr(
        genesis_entra_operation,
        "read_entra_effects",
        lambda **_kwargs: _readback(),
    )
    result = genesis_entra_operation.run_entra_operation(
        work_dir=work_dir,
        target=target,
        controls=controls,
        snapshot_directory=snapshot,
        snapshot_digest=SNAPSHOT_DIGEST,
        apply=True,
    )

    assert apply_count == 1
    assert result["state"] == "applied"
    receipt = json.loads((work_dir / "entra-only-receipt.json").read_text())
    assert receipt["recovered_from_claim"] is True
    assert receipt["effects"] == _readback().projection()


def test_same_name_group_recreated_between_claim_and_recovery_blocks_success(
    tmp_path, monkeypatch
) -> None:
    target, controls, work_dir, snapshot = _ready_runtime(tmp_path, monkeypatch)
    plan = _plan()
    monkeypatch.setattr(genesis_entra_operation, "plan_entra", lambda **_kwargs: plan)
    _approve(monkeypatch)
    apply_count = 0

    def ambiguous(_plan):
        nonlocal apply_count
        apply_count += 1
        raise RuntimeError("ambiguous-after-group-assignments")

    monkeypatch.setattr(genesis_entra_operation, "apply_entra_bounded", ambiguous)
    with pytest.raises(RuntimeError, match="ambiguous"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )

    monkeypatch.setattr(
        genesis_entra_operation,
        "apply_entra_bounded",
        lambda *_args, **_kwargs: pytest.fail("claim recovery repeated apply"),
    )

    def changed_group_readback(*, plan):
        assert dict(plan.role_groups) == ROLE_GROUPS
        raise ValueError("bounded Entra role-group name and object binding changed")

    monkeypatch.setattr(
        genesis_entra_operation,
        "read_entra_effects",
        changed_group_readback,
    )
    with pytest.raises(ValueError, match="automatic retry is blocked"):
        genesis_entra_operation.run_entra_operation(
            work_dir=work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot,
            snapshot_digest=SNAPSHOT_DIGEST,
            apply=True,
        )

    assert apply_count == 1
    assert not (work_dir / "entra-only-receipt.json").exists()
