"""Planning-only VM task runner for read surfaces without executor identity."""

from __future__ import annotations

from fdai.shared.providers.vm_task import (
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskRunner,
    VmTaskRunnerError,
    VmTaskStatus,
)


class PlanningVmTaskRunner(VmTaskRunner):
    """Return deterministic plans and structurally refuse live execution."""

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        if not request.dry_run:
            raise VmTaskRunnerError("planning runner cannot execute a VM task")
        missing = request.task.capabilities - request.target.capabilities
        if missing:
            names = ", ".join(sorted(value.value for value in missing))
            raise VmTaskRunnerError(f"target lacks required capabilities: {names}")
        return VmTaskReceipt(
            run_ref=f"plan:{request.task.artifact_hash}:{request.target.resource_ref}",
            artifact_hash=request.task.artifact_hash,
            status=VmTaskStatus.PLANNED,
            detail="validated plan; Operator API has no VM executor identity",
        )

    async def status(self, run_ref: str) -> VmTaskReceipt:
        raise VmTaskRunnerError(f"planning runner has no live status for {run_ref!r}")

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        raise VmTaskRunnerError(f"planning runner cannot cancel {run_ref!r}")


__all__ = ["PlanningVmTaskRunner"]
