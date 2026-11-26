"""Planning runner preserves the console/executor identity boundary."""

import pytest
from fdai.delivery.vm_task import PlanningVmTaskRunner
from fdai.shared.providers.vm_task import (
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskRequest,
    VmTaskRunnerError,
    VmTaskStatus,
    VmTaskTarget,
)


def _request(*, dry_run: bool) -> VmTaskRequest:
    return VmTaskRequest(
        idempotency_key="plan-1",
        task=PythonTaskSpec(
            task_id="task.example",
            version="1.0.0",
            entrypoint="main.py",
            files=(PythonTaskFile(path="main.py", content="print('ok')\n"),),
        ),
        target=VmTaskTarget(resource_ref="resource:compute/vm/example"),
        dry_run=dry_run,
    )


async def test_planning_runner_returns_plan_only() -> None:
    receipt = await PlanningVmTaskRunner().run(_request(dry_run=True))
    assert receipt.status is VmTaskStatus.PLANNED
    assert "no VM executor identity" in receipt.detail


async def test_planning_runner_refuses_live_execution() -> None:
    with pytest.raises(VmTaskRunnerError, match="cannot execute"):
        await PlanningVmTaskRunner().run(_request(dry_run=False))
