"""VM Python ToolExecutor bridge tests."""

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from fdai.delivery.vm_task import VmPythonToolExecutor, VmPythonToolExecutorConfig
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.vm_task import (
    InMemoryPythonTaskArtifactStore,
    InMemoryVmTaskRunner,
    InMemoryVmTaskTargetResolver,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallRequest, ToolError
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskReceipt,
    VmTaskStatus,
    VmTaskTarget,
)


async def _fixture() -> tuple[VmPythonToolExecutor, PythonTaskSpec, InMemoryVmTaskRunner]:
    task = PythonTaskSpec(
        task_id="gpu.health-check",
        version="1.0.0",
        entrypoint="main.py",
        files=(PythonTaskFile(path="main.py", content="print('ok')\n"),),
        capabilities=frozenset({PythonTaskCapability.GPU}),
    )
    artifacts = InMemoryPythonTaskArtifactStore()
    await artifacts.put(task, created_by="operator-1")
    targets = InMemoryVmTaskTargetResolver(
        (
            VmTaskTarget(
                resource_ref="resource:compute/vm/gpu-worker",
                capabilities=frozenset({PythonTaskCapability.GPU}),
            ),
        )
    )
    runner = InMemoryVmTaskRunner()
    executor = VmPythonToolExecutor(
        artifacts=artifacts,
        targets=targets,
        runner=runner,
        config=VmPythonToolExecutorConfig(poll_interval_seconds=0.001),
    )
    return executor, task, runner


def _request(task: PythonTaskSpec, *, mode: Mode, key: str = "run-1") -> ToolCallRequest:
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key=key,
        action_type_name="tool.run-python-on-vm",
        rule_ids=("operator.request",),
        tool_ref="resource:compute/vm/gpu-worker",
        arguments={
            "artifact_ref": task.artifact_ref,
            "target_resource_ref": "resource:compute/vm/gpu-worker",
            "reason": "Test the governed GPU task.",
        },
        labels=("shadow",) if mode is Mode.SHADOW else ("enforce",),
        mode=mode,
    )


async def test_shadow_call_returns_plan_without_execution() -> None:
    executor, task, runner = await _fixture()

    receipt = await executor.execute(_request(task, mode=Mode.SHADOW))

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert runner.requests[0].dry_run is True


async def test_enforce_call_runs_and_is_idempotent() -> None:
    executor, task, runner = await _fixture()

    first = await executor.execute(_request(task, mode=Mode.ENFORCE))
    repeated = await executor.execute(_request(task, mode=Mode.ENFORCE))

    assert first.outcome is ToolCallOutcome.SUCCEEDED
    assert runner.requests[0].dry_run is False
    assert repeated.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert len(runner.requests) == 1


async def test_artifact_version_is_immutable() -> None:
    store = InMemoryPythonTaskArtifactStore()
    first = PythonTaskSpec(
        task_id="gpu.health-check",
        version="1.0.0",
        entrypoint="main.py",
        files=(PythonTaskFile(path="main.py", content="print('a')\n"),),
    )
    changed = PythonTaskSpec(
        task_id=first.task_id,
        version=first.version,
        entrypoint=first.entrypoint,
        files=(PythonTaskFile(path="main.py", content="print('b')\n"),),
    )
    await store.put(first, created_by="operator-1")

    try:
        await store.put(changed, created_by="operator-1")
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:  # pragma: no cover - assertion helper
        raise AssertionError("artifact store accepted a rewritten version")


@pytest.mark.parametrize(
    "arguments",
    (
        {
            "artifact_ref": "not-an-artifact",
            "target_resource_ref": "resource:compute/vm/gpu-worker",
        },
        {
            "artifact_ref": "python-task:gpu.health-check@1.0.0#" + "a" * 64,
            "target_resource_ref": "x" * 2_049,
        },
    ),
)
async def test_rejects_unbounded_or_invalid_references(arguments: dict[str, str]) -> None:
    executor, task, _runner = await _fixture()
    request = replace(
        _request(task, mode=Mode.ENFORCE),
        arguments={**arguments, "reason": "Run the governed GPU task."},
    )

    with pytest.raises(ToolError, match="artifact_ref|target_resource_ref"):
        await executor.execute(request)


class _PollingFailureRunner:
    def __init__(self, *, cancel_fails: bool = False) -> None:
        self.cancel_calls = 0
        self.cancel_fails = cancel_fails

    async def run(self, request):  # type: ignore[no-untyped-def]
        return VmTaskReceipt(
            run_ref="vm-task:running",
            artifact_hash=request.task.artifact_hash,
            status=VmTaskStatus.SUBMITTED,
            detail="submitted",
        )

    async def status(self, run_ref: str) -> VmTaskReceipt:
        raise RuntimeError(f"status unavailable for {run_ref}")

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        self.cancel_calls += 1
        if self.cancel_fails:
            raise RuntimeError("cancel unavailable")
        return VmTaskReceipt(
            run_ref=run_ref,
            artifact_hash="a" * 64,
            status=VmTaskStatus.CANCELLED,
            detail="cancelled after polling failure",
        )


async def _polling_executor(runner, *, sleep=None):  # type: ignore[no-untyped-def]
    task = PythonTaskSpec(
        task_id="gpu.health-check",
        version="1.0.0",
        entrypoint="main.py",
        files=(PythonTaskFile(path="main.py", content="print('ok')\n"),),
        capabilities=frozenset({PythonTaskCapability.GPU}),
    )
    artifacts = InMemoryPythonTaskArtifactStore()
    await artifacts.put(task, created_by="operator-1")
    targets = InMemoryVmTaskTargetResolver(
        (
            VmTaskTarget(
                resource_ref="resource:compute/vm/gpu-worker",
                capabilities=frozenset({PythonTaskCapability.GPU}),
            ),
        )
    )
    return (
        VmPythonToolExecutor(
            artifacts=artifacts,
            targets=targets,
            runner=runner,
            config=VmPythonToolExecutorConfig(poll_interval_seconds=0.001),
            sleep=sleep or asyncio.sleep,
        ),
        task,
    )


async def test_polling_failure_cancels_remote_run() -> None:
    runner = _PollingFailureRunner()
    executor, task = await _polling_executor(runner)

    receipt = await executor.execute(_request(task, mode=Mode.ENFORCE))

    assert receipt.outcome is ToolCallOutcome.STOPPED
    assert runner.cancel_calls == 1


async def test_polling_and_cancel_failure_surfaces_failed_tool_call() -> None:
    runner = _PollingFailureRunner(cancel_fails=True)
    executor, task = await _polling_executor(runner)

    with pytest.raises(ToolError, match="cancellation could not be confirmed"):
        await executor.execute(_request(task, mode=Mode.ENFORCE))
    assert runner.cancel_calls == 1


async def test_coroutine_cancellation_attempts_remote_cancel() -> None:
    runner = _PollingFailureRunner()

    async def cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    executor, task = await _polling_executor(runner, sleep=cancel_sleep)

    with pytest.raises(asyncio.CancelledError):
        await executor.execute(_request(task, mode=Mode.ENFORCE))
    assert runner.cancel_calls == 1
