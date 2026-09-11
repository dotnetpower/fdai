"""Local exact Foundation apply boundary regressions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_foundation_apply as apply  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest  # noqa: E402

BINDING = "a" * 64
PLAN_DIGEST = "b" * 64
REVIEW_DIGEST = "c" * 64
SOURCE = "d" * 40
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"


def _profile() -> ProvisionProfile:
    return ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding=BINDING,
        connectivity="offline",
        host="managed-vm",
        transport="manual",
        access_method="bastion",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=500,
    )


def _review() -> dict[str, object]:
    return {
        "schema_version": "fdai.foundation-saved-plan.v1",
        "state": "review",
        "review_digest": REVIEW_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "context": {
            "offline_manifest_digest": "e" * 64,
            "deployment_bundle_digest": "f" * 64,
            "profile_digest": "1" * 64,
            "target_binding": BINDING,
            "variables_digest": "2" * 64,
            "terraform_digest": "3" * 64,
            "provider_lock_digest": "4" * 64,
            "run_digest": "5" * 64,
            "foundation_context_digest": "6" * 64,
            "source_commit": SOURCE,
        },
    }


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--plan-directory",
        str(tmp_path / "plan"),
        "--profile",
        str(tmp_path / "profile.json"),
        "--variables-file",
        str(tmp_path / "variables.json"),
        "--offline-kit",
        str(tmp_path / "kit"),
        "--release-root",
        str(tmp_path / "release.pub"),
        "--bundle-public-key",
        str(tmp_path / "bundle.pub"),
        "--expected-review-digest",
        REVIEW_DIGEST,
        "--expected-plan-digest",
        PLAN_DIGEST,
        "--repository",
        "example/repository",
        "--timeout-seconds",
        "900",
        *extra,
    ]


def _mock_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    plan = tmp_path / "plan"
    plan.mkdir(mode=0o700)
    monkeypatch.setattr(apply, "load_profile", lambda _: _profile())
    monkeypatch.setattr(
        apply,
        "verify_foundation_plan",
        lambda **_: {"plan_digest": PLAN_DIGEST, "integrity_verified": True},
    )
    monkeypatch.setattr(apply, "_foundation_review", lambda _: _review())

    def target(**kwargs: object) -> tuple[str, str]:
        Path(str(kwargs["destination"])).write_text("{}", encoding="utf-8")
        Path(str(kwargs["destination"])).chmod(0o600)
        return SUBSCRIPTION, TENANT

    monkeypatch.setattr(apply, "_foundation_target", target)
    monkeypatch.setattr(apply.GenesisChecks, "verify_target", lambda *a, **kw: None)
    monkeypatch.setattr(apply.GenesisChecks, "verify_source", lambda *a, **kw: None)
    monkeypatch.setattr(apply, "_capture", lambda *a, **kw: SOURCE + "\n")
    terraform = tmp_path / "terraform"
    terraform.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    terraform.chmod(0o755)
    snapshot = SimpleNamespace(
        terraform=terraform,
        infra_root=tmp_path,
        data_dir=tmp_path / "data",
        cli_config=tmp_path / "terraform.rc",
        cleanup=lambda: None,
    )
    monkeypatch.setattr(apply, "_prepare_verified_snapshot", lambda **_: snapshot)
    monkeypatch.setattr(apply, "_terraform_environment", lambda **_: {})
    calls: list[str] = []

    def required(command: list[str], **_: object) -> None:
        stage = command[1]
        calls.append(stage)
        if stage == "apply":
            assert (plan / apply.CLAIM_NAME).is_file()

    monkeypatch.setattr(apply, "_required", required)

    def claim(**_: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "fdai.genesis-foundation-apply-claim.v1",
            "state": "applying",
            "review_digest": REVIEW_DIGEST,
            "plan_digest": PLAN_DIGEST,
            "target_binding": BINDING,
            "actor_digest": "7" * 64,
            "idempotency_key": canonical_digest(
                {"target_binding": BINDING, "plan_digest": PLAN_DIGEST}
            ),
            "claimed_at": "2026-09-10T00:00:00+00:00",
            "mutation_performed": False,
            "subscription_ready": False,
        }
        return value

    monkeypatch.setattr(apply, "_claim", claim)

    def receipt(**_: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "fdai.genesis-foundation-apply-receipt.v1",
            "state": "applied",
            "review_digest": REVIEW_DIGEST,
            "plan_digest": PLAN_DIGEST,
            "target_binding": BINDING,
            "source_commit": SOURCE,
            "state_digest": "8" * 64,
            "state_ref": (
                "foundation-apply-bundle/example/infra/genesis-foundation/terraform.tfstate"
            ),
            "handoff_digest": "9" * 64,
            "control_plane_readback_verified": True,
            "zero_change_verified": True,
            "remote_backend_authority_verified": False,
            "runner_attested": False,
            "mutation_performed": True,
            "subscription_ready": False,
            "completed_at": "2026-09-10T00:01:00+00:00",
        }
        value["receipt_digest"] = canonical_digest(value)
        return value

    monkeypatch.setattr(apply, "_verify_foundation_effect", receipt)
    return plan, calls


def test_apply_requires_explicit_exact_approval_before_artifact_or_azure_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("apply prerequisites must not run without explicit approval")

    monkeypatch.setattr(apply, "load_profile", forbidden)
    assert apply.main(_args(tmp_path)) == 3


def test_exact_apply_writes_claim_before_effect_and_never_reapplies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, calls = _mock_execution(tmp_path, monkeypatch)
    arguments = _args(tmp_path, "--approve", "--output", "json")

    assert apply.main(arguments) == 0
    assert calls == ["init", "apply"]
    assert (plan / apply.CLAIM_NAME).is_file()
    assert (plan / apply.RECEIPT_NAME).is_file()
    assert not (plan / ".foundation-apply-input.json").exists()

    assert apply.main(arguments) == 0
    assert calls == ["init", "apply", "init"]


def test_resume_requires_claim_and_skips_terraform_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, calls = _mock_execution(tmp_path, monkeypatch)
    arguments = _args(tmp_path, "--resume-verification", "--output", "json")

    assert apply.main(arguments) == 3
    assert calls == []
    (plan / apply.CLAIM_NAME).write_text(
        json.dumps(apply._claim(review=_review(), target_binding=BINDING)) + "\n",
        encoding="utf-8",
    )
    (plan / apply.CLAIM_NAME).chmod(0o600)
    assert apply.main(arguments) == 0
    assert calls == ["init"]


def test_completed_state_handoff_reobserves_control_plane_without_local_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, calls = _mock_execution(tmp_path, monkeypatch)
    arguments = _args(tmp_path, "--approve", "--output", "json")
    assert apply.main(arguments) == 0
    marker = plan / "foundation-state-handoff-receipt.json"
    marker.write_text("{}\n", encoding="utf-8")
    marker.chmod(0o600)
    observed: list[str] = []
    monkeypatch.setattr(
        apply,
        "_reobserve_completed_foundation",
        lambda **_: observed.append("control-plane"),
    )

    assert apply.main(arguments) == 0

    assert observed == ["control-plane"]
    assert calls == ["init", "apply"]


def _handoff() -> dict[str, object]:
    app_id = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-dev-krc"
    state_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-ops-krc/"
        "providers/Microsoft.Storage/storageAccounts/example"
    )
    identity_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-ops-krc/"
        "providers/Microsoft.ManagedIdentity/userAssignedIdentities/example"
    )
    return {
        "terraform_root": "infra/genesis-foundation",
        "source_commit": SOURCE,
        "run_digest": "5" * 64,
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "region": "koreacentral",
        "app_resource_group": {"id": app_id},
        "ops": {"resource_group_name": "rg-example-ops-krc"},
        "state": {
            "account_id": state_id,
            "container_name": "tfstate",
            "plan_container": "deployment-plans",
        },
        "runner": {
            "vm_name": "vm-runner-example-dev-krc",
            "vm_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-ops-krc/"
                "providers/Microsoft.Compute/virtualMachines/vm-runner-example-dev-krc"
            ),
            "admin_username": "fdairunner",
            "parallelism": 1,
            "ssh_key_digest": "7" * 64,
            "public_egress": True,
            "identity_id": identity_id,
        },
        "access": {
            "method": "bastion",
            "bastion_name": "bas-runner-example-dev-krc",
            "bastion_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-ops-krc/"
                "providers/Microsoft.Network/bastionHosts/bas-runner-example-dev-krc"
            ),
        },
    }


def test_independent_readback_requires_private_keyless_state_and_exact_runner_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff()
    state = handoff["state"]
    app_group = handoff["app_resource_group"]
    runner = handoff["runner"]
    assert isinstance(state, dict) and isinstance(app_group, dict) and isinstance(runner, dict)

    def capture(command: list[str], **_: object) -> str:
        if command[:3] == ["az", "group", "show"]:
            return json.dumps({"id": app_group["id"]})
        if command[:3] == ["az", "resource", "show"] and command[-1] == "json":
            return json.dumps(
                {
                    "id": state["account_id"],
                    "properties": {
                        "publicNetworkAccess": "Disabled",
                        "allowSharedKeyAccess": False,
                        "minimumTlsVersion": "TLS1_2",
                    },
                }
            )
        if command[:3] == ["az", "resource", "show"]:
            return ""
        if command[:3] == ["az", "vm", "show"]:
            return json.dumps(
                {
                    "id": runner["vm_id"],
                    "provisioningState": "Succeeded",
                    "identity": {"userAssignedIdentities": {runner["identity_id"]: {}}},
                }
            )
        if command[:4] == ["az", "network", "bastion", "show"]:
            access = handoff["access"]
            assert isinstance(access, dict)
            return json.dumps(
                {
                    "id": access["bastion_id"],
                    "name": access["bastion_name"],
                    "provisioningState": "Succeeded",
                    "sku": "Standard",
                    "tunneling": True,
                }
            )
        raise AssertionError(command)

    monkeypatch.setattr(apply, "_capture", capture)
    apply._independent_readback(handoff, tmp_path)

    def public_account(command: list[str], **kwargs: object) -> str:
        result = capture(command, **kwargs)
        if command[:3] == ["az", "resource", "show"] and command[-1] == "json":
            value = json.loads(result)
            value["properties"]["publicNetworkAccess"] = "Enabled"
            return json.dumps(value)
        return result

    monkeypatch.setattr(apply, "_capture", public_account)
    with pytest.raises(ValueError, match="state protection"):
        apply._independent_readback(handoff, tmp_path)
