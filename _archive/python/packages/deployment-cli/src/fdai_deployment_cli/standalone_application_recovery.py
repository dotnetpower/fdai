"""Bounded same-invocation recovery for managed-host application stages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fdai_deployment_cli.deployment_deadline import DeploymentDeadline

RemoteJson = Callable[..., dict[str, Any]]
PlanAfterRecovery = Callable[..., tuple[dict[str, Any], str]]
ApprovePlan = Callable[..., Path]
RequireReceipt = Callable[[dict[str, Any], str], None]


def converge_focused_private_access(
    tunnel: Any,
    *,
    remote_root: str,
    app_work: str,
    prepared_root: Path,
    remote_approval: str,
    deadline: DeploymentDeadline,
    remote_json: RemoteJson,
    plan_after_recovery: PlanAfterRecovery,
    approve_plan: ApprovePlan,
    require_receipt: RequireReceipt,
) -> dict[str, Any]:
    recovery = remote_json(
        tunnel,
        remote_root,
        app_work,
        ("recover-apply", "--stage", "access"),
        timeout=deadline.remaining(3600),
    )
    if recovery.get("state") == "applied":
        require_receipt(recovery, "access")
        return recovery
    review, command = plan_after_recovery(
        tunnel,
        remote_root,
        app_work,
        recovery,
        stage="access",
        timeout=deadline.remaining(3600),
    )
    approval = approve_plan(prepared_root, review, deadline=deadline)
    tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
    tunnel.copy_to(approval, remote_approval, timeout=120)
    try:
        receipt = remote_json(
            tunnel,
            remote_root,
            app_work,
            (command, "--stage", "access", "--approval", remote_approval),
            timeout=deadline.remaining(7200),
        )
    finally:
        approval.unlink(missing_ok=True)
        tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
    require_receipt(receipt, "access")
    return receipt


def recover_failed_exact_apply(
    tunnel: Any,
    *,
    remote_root: str,
    app_work: str,
    prepared_root: Path,
    remote_approval: str,
    stage: str,
    deadline: DeploymentDeadline,
    remote_json: RemoteJson,
    plan_after_recovery: PlanAfterRecovery,
    approve_plan: ApprovePlan,
) -> dict[str, Any]:
    """Verify a failed exact apply, then apply only its separately approved residual."""
    for phase in range(2):
        recovery = remote_json(
            tunnel,
            remote_root,
            app_work,
            ("recover-apply", "--stage", stage),
            timeout=deadline.remaining(3600),
        )
        if recovery.get("state") == "applied":
            return recovery
        review, command = plan_after_recovery(
            tunnel,
            remote_root,
            app_work,
            recovery,
            stage=stage,
            timeout=deadline.remaining(3600),
        )
        if command != "apply-residual":
            raise ValueError("failed exact apply did not produce bounded residual recovery")
        approval = approve_plan(prepared_root, review, deadline=deadline)
        tunnel.copy_to(approval, remote_approval, timeout=120)
        try:
            return remote_json(
                tunnel,
                remote_root,
                app_work,
                (command, "--stage", stage, "--approval", remote_approval),
                timeout=deadline.remaining(7200),
            )
        except ValueError:
            if phase == 1:
                raise
        finally:
            approval.unlink(missing_ok=True)
            tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
    raise ValueError("failed exact apply exceeded its bounded residual recovery")
