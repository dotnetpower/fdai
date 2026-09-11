"""Resumable private Genesis coordinator regressions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

from genesis_approval import GenesisApproval  # noqa: E402
from genesis_checks import GenesisChecks  # noqa: E402
from genesis_foundation import FoundationPlanInputs  # noqa: E402
from genesis_private_errors import (  # noqa: E402
    PrivateExecutionError,
    PrivateExecutionWaitError,
)
from genesis_private_execution import (  # noqa: E402
    PrivateExecutionConfig,
    PrivateExecutionCoordinator,
)
from genesis_private_plan_summary import summarize_plan  # noqa: E402
from genesis_status import StatusStore  # noqa: E402

SOURCE = "a" * 40
RUN_BINDING = "b" * 64
REVIEW_DIGEST = "c" * 64
PLAN_DIGEST = "d" * 64
FOUNDATION_RECEIPT_DIGEST = "e" * 64


def _inputs(tmp_path: Path) -> FoundationPlanInputs:
    return FoundationPlanInputs(
        offline_kit=tmp_path / "kit",
        release_root=tmp_path / "release.pem",
        bundle_public_key=tmp_path / "bundle.pem",
        profile=tmp_path / "profile.json",
        variables_file=tmp_path / "variables.json",
    )


def _store(tmp_path: Path) -> StatusStore:
    work = tmp_path / "run"
    work.mkdir(mode=0o700)
    return StatusStore(
        path=work / "status.json",
        source_commit=SOURCE,
        target_binding=RUN_BINDING,
        mode="apply",
        deadline_at="2999-09-10T12:00:00Z",
    )


def _config(
    tmp_path: Path, *, approval: GenesisApproval | None = None, private_key: Path | None = None
) -> PrivateExecutionConfig:
    return PrivateExecutionConfig(
        repository_root=ROOT,
        repository="example/repository",
        subscription_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        source_commit=SOURCE,
        work_dir=tmp_path / "run",
        foundation_inputs=_inputs(tmp_path),
        approval=approval,
        approval_path=tmp_path / "approval.json" if approval is not None else None,
        create_runner_image=False,
        runner_image_terraform=None,
        runner_ssh_private_key=private_key,
        execution_timeout_seconds=3600,
    )


def _plan() -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-1",
        "attempt": 1,
        "review_digest": REVIEW_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "expires_at": "2999-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _coordinator(
    tmp_path: Path,
    *,
    approval: GenesisApproval | None = None,
    run_child: object | None = None,
) -> PrivateExecutionCoordinator:
    store = _store(tmp_path)
    checks = GenesisChecks(ROOT)
    checks.verify_checkout_unchanged = lambda: None  # type: ignore[method-assign]
    kwargs: dict[str, object] = {
        "config": _config(tmp_path, approval=approval),
        "store": store,
        "checks": checks,
        "prepare_plan": lambda **_: _plan(),
    }
    if run_child is not None:
        kwargs["run_child"] = run_child
    return PrivateExecutionCoordinator(**kwargs)  # type: ignore[arg-type]


def test_foundation_plan_waits_without_exact_approval(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)

    with pytest.raises(PrivateExecutionWaitError) as raised:
        coordinator.run()

    assert raised.value.stage == "foundation-apply"
    assert raised.value.reason_code == "foundation_exact_plan_approval_required"
    payload = coordinator.store.payload
    assert payload["completed_stages"][-3:] == [
        "runner-image-plan",
        "runner-image-apply",
        "foundation-plan",
    ]
    assert payload["skipped_stages"] == ["runner-image-plan", "runner-image-apply"]
    foundation = payload["foundation_report"]
    assert isinstance(foundation, dict)
    assert foundation["foundation_plan"] == _plan()


def test_another_stage_approval_grants_no_foundation_authority(tmp_path: Path) -> None:
    approval = GenesisApproval(
        stage="runner-enrollment",
        actor_digest="9" * 64,
        evidence={"foundation_receipt_digest": FOUNDATION_RECEIPT_DIGEST},
    )
    coordinator = _coordinator(tmp_path, approval=approval)

    with pytest.raises(PrivateExecutionWaitError) as raised:
        coordinator.run()

    assert raised.value.stage == "foundation-apply"
    assert raised.value.reason_code == "foundation_exact_plan_approval_required"


def test_changed_digest_rejects_the_current_stage_approval(tmp_path: Path) -> None:
    approval = GenesisApproval(
        stage="foundation-apply",
        actor_digest="9" * 64,
        evidence={"review_digest": REVIEW_DIGEST, "plan_digest": "f" * 64},
    )
    coordinator = _coordinator(tmp_path, approval=approval)

    with pytest.raises(PrivateExecutionError) as raised:
        coordinator.run()

    assert raised.value.stage == "foundation-apply"
    assert raised.value.reason_code == "genesis_approval_evidence_mismatch"


@pytest.mark.parametrize(
    "evidence_name",
    ("foundation-apply-claim.json", "foundation-apply-receipt.json"),
)
def test_started_foundation_effect_selects_verification_only_resume(
    tmp_path: Path, evidence_name: str
) -> None:
    calls: list[tuple[str, ...]] = []

    def child(arguments: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        result = {
            "schema_version": "fdai.genesis-foundation-apply-receipt.v1",
            "state": "applied",
            "review_digest": REVIEW_DIGEST,
            "plan_digest": PLAN_DIGEST,
            "handoff_digest": "1" * 64,
            "control_plane_readback_verified": True,
            "zero_change_verified": True,
            "remote_backend_authority_verified": False,
            "runner_attested": False,
            "mutation_performed": True,
            "subscription_ready": False,
            "completed_at": "2026-09-10T00:00:00+00:00",
            "receipt_digest": FOUNDATION_RECEIPT_DIGEST,
        }
        return subprocess.CompletedProcess(arguments, 0, json.dumps(result), "")

    coordinator = _coordinator(tmp_path, run_child=child)
    plan_directory = tmp_path / "run" / "foundation-plan-attempt-1"
    plan_directory.mkdir(mode=0o700)
    (plan_directory / evidence_name).write_text("{}\n", encoding="utf-8")
    (plan_directory / evidence_name).chmod(0o600)

    inputs = _inputs(tmp_path)
    result = coordinator._run_foundation_apply(
        inputs,
        inputs.variables_file,
        _plan(),
    )

    assert result["receipt_digest"] == FOUNDATION_RECEIPT_DIGEST
    assert len(calls) == 1
    assert calls[0][0] == "/bin/bash"
    assert "--resume-verification" in calls[0]
    assert "--approve" not in calls[0]


def test_portable_checkpoint_projection_drops_resource_ids_and_state_paths(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    raw = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": REVIEW_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "toolchain_digest": "1" * 64,
        "runner_image_id": "/subscriptions/private/resourceGroups/private/providers/image",
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
        "receipt_digest": "2" * 64,
    }

    coordinator._record_checkpoint(
        stage="runner-image-apply",
        checkpoint="runner-image-apply",
        state="applied",
        field="runner_image_apply",
        result=raw,
        completed=True,
    )

    serialized = json.dumps(coordinator.store.payload)
    assert "runner_image_id" not in serialized
    assert "terraform.tfstate" not in serialized
    assert "/subscriptions/" not in serialized


def test_plan_summary_contains_only_bounded_action_and_type_counts() -> None:
    plan = {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": "module.private.azurerm_resource_group.example",
                "mode": "managed",
                "type": "azurerm_resource_group",
                "change": {
                    "actions": ["create"],
                    "after": {"name": "private-resource-name"},
                },
            },
            {
                "address": "module.private.azurerm_role_assignment.example",
                "mode": "managed",
                "type": "azurerm_role_assignment",
                "change": {
                    "actions": ["delete", "create"],
                    "before": {"principal_id": "private-principal"},
                    "after": {"principal_id": "another-private-principal"},
                },
            },
            {
                "address": "data.azurerm_client_config.current",
                "mode": "data",
                "type": "azurerm_client_config",
                "change": {"actions": ["read"]},
            },
        ],
    }

    result = summarize_plan(plan)

    assert result["action_counts"] == {
        "create": 1,
        "delete": 0,
        "no_op": 0,
        "read": 0,
        "replace": 1,
        "update": 0,
    }
    assert result["resource_type_counts"] == {
        "azurerm_resource_group": {"create": 1},
        "azurerm_role_assignment": {"replace": 1},
    }
    assert result["destructive"] is True
    serialized = json.dumps(result)
    assert "private-resource-name" not in serialized
    assert "private-principal" not in serialized
    assert "address" not in serialized


def test_plan_summary_rejects_unknown_action_shape() -> None:
    with pytest.raises(ValueError, match="actions are unsupported"):
        summarize_plan(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {
                        "mode": "managed",
                        "type": "azurerm_resource_group",
                        "change": {"actions": ["forget"]},
                    }
                ],
            }
        )
