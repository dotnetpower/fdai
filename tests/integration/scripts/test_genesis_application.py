"""Protected application orchestration regressions for supervised Genesis."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_application  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest  # noqa: E402
from fdai_deployment_cli.github_actions import WorkflowDispatch  # noqa: E402
from fdai_deployment_cli.profile import write_profile  # noqa: E402

SOURCE = "a" * 40
RUN_BINDING = "b" * 64
TARGET = "c" * 64


def _summary(create: int) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "fdai.deployment-plan-summary.v1",
        "action_counts": {
            "create": create,
            "update": 0,
            "delete": 0,
            "replace": 0,
            "no_op": 0,
            "read": 0,
        },
        "resource_type_counts": ({"azurerm_resource_group": {"create": create}} if create else {}),
        "managed_resources": create,
        "destructive": False,
    }
    body["summary_digest"] = canonical_digest(body)
    return body


def _config(tmp_path: Path) -> genesis_application.ApplicationConfig:
    tmp_path.chmod(0o700)
    profile = tmp_path / "profile.json"
    write_profile(
        profile,
        ProvisionProfile(
            environment="dev",
            region="koreacentral",
            target_binding=TARGET,
            connectivity="offline",
            host="managed-vm",
            transport="manual",
            access_method="bastion",
            shadow_only=True,
            approval_quorum=1,
            monthly_cost_ceiling=1000,
        ),
    )
    return genesis_application.ApplicationConfig(
        repository="example/fdai",
        source_commit=SOURCE,
        run_id="run-1",
        run_binding=RUN_BINDING,
        profile=profile,
        work_dir=tmp_path,
        actor_digest="d" * 64,
    )


def _plan(create: int) -> dict[str, object]:
    return {
        "plan_id": f"plan-{create + 1}-1",
        "plan_digest": ("e" if create else "f") * 64,
        "context_digest": "1" * 64,
        "expires_at": "2099-01-01T00:00:00Z",
        "expired": False,
        "plan_summary": _summary(create),
        "post_apply_observations": [],
    }


def _apply_receipt() -> dict[str, object]:
    return {
        "plan_id": "plan-2-1",
        "plan_digest": "e" * 64,
        "request_id": "apply-request",
        "context_digest": "1" * 64,
        "source_commit": SOURCE,
        "status": "applied",
        "terraform_zero_change_verified": True,
        "migration_stage_verified": True,
        "runtime_health_verified": True,
        "canary_verified": True,
        "initial_inventory_execution_receipt_digest": "2" * 64,
        "subscription_ready": False,
    }


def test_application_runs_plan_apply_and_zero_change_convergence(
    tmp_path: Path, monkeypatch
) -> None:
    plans = iter((_plan(1), _plan(0)))
    dispatches = []

    def dispatch_plan(**kwargs):
        dispatches.append(("plan", kwargs))
        return WorkflowDispatch("plan-" + "1" * 48, "plan", "1" * 64, "plan")

    def dispatch_apply(**kwargs):
        dispatches.append(("apply", kwargs))
        return WorkflowDispatch("apply-" + "2" * 48, "apply", "1" * 64, "apply")

    def wait(**kwargs):
        if kwargs.get("expected_plan_id"):
            return {
                "status": "completed",
                "conclusion": "success",
                "apply_receipt": _apply_receipt(),
            }
        return {"status": "completed", "conclusion": "success", "plan": next(plans)}

    monkeypatch.setattr(genesis_application, "dispatch_plan", dispatch_plan)
    monkeypatch.setattr(genesis_application, "dispatch_apply", dispatch_apply)
    monkeypatch.setattr(genesis_application, "_wait_for_workflow", wait)
    monkeypatch.setattr(genesis_application, "_approval_digest", lambda *_: "3" * 64)

    receipt = genesis_application.run_application(_config(tmp_path))

    assert [item[0] for item in dispatches] == ["plan", "apply", "plan"]
    assert receipt["terraform_zero_change_verified"] is True
    assert receipt["initial_inventory_execution_succeeded"] is True
    assert receipt["active_inventory_generation_verified"] is False
    assert receipt["subscription_ready"] is False


def test_application_failed_apply_resumes_verification_without_new_approval(
    tmp_path: Path, monkeypatch
) -> None:
    plans = iter((_plan(1), _plan(0)))
    apply_calls = []
    apply_statuses = iter(
        (
            {"status": "completed", "conclusion": "failure"},
            {"status": "completed", "conclusion": "success", "apply_receipt": _apply_receipt()},
        )
    )

    monkeypatch.setattr(
        genesis_application,
        "dispatch_plan",
        lambda **_: WorkflowDispatch("plan-" + "1" * 48, "plan", "1" * 64, "plan"),
    )

    def dispatch_apply(**kwargs):
        apply_calls.append(kwargs)
        return WorkflowDispatch(
            "apply-" + str(len(apply_calls)) * 48,
            "apply",
            "1" * 64,
            "resume-verification" if kwargs["resume_verification"] else "apply",
        )

    def wait(**kwargs):
        if kwargs.get("expected_plan_id"):
            return next(apply_statuses)
        return {"status": "completed", "conclusion": "success", "plan": next(plans)}

    monkeypatch.setattr(genesis_application, "dispatch_apply", dispatch_apply)
    monkeypatch.setattr(genesis_application, "_wait_for_workflow", wait)
    monkeypatch.setattr(genesis_application, "_approval_digest", lambda *_: "3" * 64)

    genesis_application.run_application(_config(tmp_path))

    assert [call["resume_verification"] for call in apply_calls] == [False, True]
