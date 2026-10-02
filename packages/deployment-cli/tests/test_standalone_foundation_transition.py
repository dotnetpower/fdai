from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli import standalone_foundation_transition as transition
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import write_private_bytes


def _review(tmp_path: Path, *, delete: int = 0, replace: int = 0) -> dict[str, object]:
    plan = tmp_path / "foundation-plan-attempt-1"
    plan.mkdir(mode=0o700)
    counts = {
        "create": 1 if not delete and not replace else 0,
        "update": 0,
        "delete": delete,
        "replace": replace,
        "read": 0,
        "no-op": 8,
    }
    review: dict[str, object] = {
        "schema_version": "fdai.foundation-saved-plan.v1",
        "state": "review",
        "apply_authorized": False,
        "source_eligibility_verified": False,
        "plan_origin_verified": False,
        "subscription_ready": False,
        "mutation_performed": False,
        "context": {
            "source_commit": "a" * 40,
            "target_binding": "b" * 64,
        },
        "plan_digest": "c" * 64,
        "plan_json_digest": "d" * 64,
        "summary": {
            "action_counts": counts,
            "resource_type_counts": {"azurerm_role_assignment": sum(counts.values())},
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
        },
        "terraform_version": "1.9.8",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0).isoformat(),
    }
    review["review_digest"] = canonical_digest(review)
    write_private_bytes(plan / "foundation-plan.json", json.dumps(review).encode())
    return review


def test_nondestructive_foundation_transition_needs_no_extra_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _review(tmp_path)
    monkeypatch.setattr(
        transition,
        "_approval_input",
        lambda **_kwargs: pytest.fail("non-destructive plan should not prompt"),
    )

    transition.approve_transition_plan(tmp_path / "foundation-plan-attempt-1")


def test_destructive_foundation_transition_requires_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _review(tmp_path, delete=1)
    monkeypatch.setattr(transition, "_approval_input", lambda **_kwargs: "wrong")

    with pytest.raises(ValueError, match="destructive Foundation transition approval was denied"):
        transition.approve_transition_plan(tmp_path / "foundation-plan-attempt-1")


def test_destructive_foundation_transition_accepts_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _review(tmp_path, replace=1)
    monkeypatch.setattr(
        transition,
        "_approval_input",
        lambda **_kwargs: "foundation-transition-apply-destructive",
    )

    transition.approve_transition_plan(tmp_path / "foundation-plan-attempt-1")


def test_transition_receipt_binds_adoption_and_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = _review(tmp_path)
    adoption = {
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
    monkeypatch.setattr(
        transition,
        "write_lineage_adoption_receipt",
        lambda **_kwargs: adoption,
    )

    receipt = transition.bind_foundation_lineage_transition(
        run_root=tmp_path,
        plan_ref="foundation-plan-attempt-1",
        application_source_commit="b" * 40,
        kit_manifest_digest="9" * 64,
        runtime_release_digest="0" * 64,
        tenant_id="00000000-0000-0000-0000-000000000001",
        subscription_id="00000000-0000-0000-0000-000000000002",
        region="westus3",
        monthly_cost_ceiling=1000,
    )

    assert receipt["transition_review_digest"] == review["review_digest"]
    assert receipt["foundation_adoption_receipt_digest"] == adoption["receipt_digest"]
    assert receipt["destructive_action_count"] == 0
    assert (tmp_path / "foundation-lineage-transition-receipt.json").is_file()
