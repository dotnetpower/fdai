"""VM task runner protocol behavior."""

from fdai.shared.providers.testing.vm_task import InMemoryVmTaskRunner
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskRequest,
    VmTaskStatus,
    VmTaskTarget,
)


def _request(*, dry_run: bool = True, key: str = "run-1") -> VmTaskRequest:
    task = PythonTaskSpec(
        task_id="gpu.health-check",
        version="1.0.0",
        entrypoint="main.py",
        files=(PythonTaskFile(path="main.py", content="print('ok')\n"),),
        capabilities=frozenset({PythonTaskCapability.GPU}),
    )
    return VmTaskRequest(
        idempotency_key=key,
        task=task,
        target=VmTaskTarget(
            resource_ref="resource:compute/vm/gpu-worker",
            capabilities=frozenset({PythonTaskCapability.GPU}),
        ),
        dry_run=dry_run,
    )


async def test_dry_run_plans_without_execution() -> None:
    runner = InMemoryVmTaskRunner()

    receipt = await runner.run(_request())

    assert receipt.status is VmTaskStatus.PLANNED
    assert receipt.exit_code is None
    assert "no code executed" in receipt.detail


async def test_live_fake_is_idempotent_and_cancelable() -> None:
    runner = InMemoryVmTaskRunner()
    first = await runner.run(_request(dry_run=False))
    repeated = await runner.run(_request(dry_run=False))
    cancelled = await runner.cancel(first.run_ref)

    assert first.status is VmTaskStatus.SUCCEEDED
    assert repeated.already_existed is True
    assert len(runner.requests) == 1
    assert cancelled.status is VmTaskStatus.CANCELLED
    assert (await runner.status(first.run_ref)).status is VmTaskStatus.CANCELLED


async def test_target_must_advertise_required_capabilities() -> None:
    runner = InMemoryVmTaskRunner()
    request = _request()
    incompatible = VmTaskRequest(
        idempotency_key="run-missing-gpu",
        task=request.task,
        target=VmTaskTarget(resource_ref=request.target.resource_ref),
    )

    try:
        await runner.run(incompatible)
    except ValueError as exc:
        assert "target lacks required capabilities: gpu" in str(exc)
    else:  # pragma: no cover - assertion helper
        raise AssertionError("runner accepted an incompatible target")
