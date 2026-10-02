from __future__ import annotations

import json
import hashlib
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
    assert calls == ["plan", "apply"]
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
