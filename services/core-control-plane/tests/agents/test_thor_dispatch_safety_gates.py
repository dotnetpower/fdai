"""Earlier safety gates must still block the new dispatch observation and executor."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.thor_execution import (
    ExecutionResourceUnavailableError,
    execute,
    invoke_executor,
)
from fdai.agents._framework.thor_preflight import PreflightSimulationResult
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.core.operational_context.test_context_dispatch import (
    TestContextDispatchBinding as DispatchBinding,
)
from fdai.shared.contracts.models import Autonomy

from tests.agents.test_thor_dispatch_start import NOW, _RecordingStore, _run


def _authorized_run() -> ActionRun:
    run = _run()
    run.state = ActionRunState.VERDICTED
    run.resolved_autonomy_ceiling = Autonomy.ENFORCE_AUTO
    return run


@pytest.mark.parametrize("failure", ["timeout", "error", "empty", "oversized"])
async def test_failed_audit_never_reaches_dispatch_observation(failure: str) -> None:
    recorder = AsyncMock(return_value="" if failure == "empty" else "x" * 513)
    if failure in {"timeout", "error"}:
        recorder.side_effect = TimeoutError() if failure == "timeout" else RuntimeError("audit")
    executor = AsyncMock(return_value=True)
    host = Thor(
        executor=executor,
        execution_audit_recorder=recorder,
        require_execution_audit=True,
        clock=lambda: NOW,
    )
    run = _authorized_run()
    await execute(host, run)
    expected = failure if failure in {"timeout", "error"} else "invalid"
    if expected == "error":
        expected = "failed"
    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == f"execution_audit_{expected}"
    executor.assert_not_awaited()
    assert not any(key.startswith("dispatch_start:") for key in host.behavior_snapshot())


async def test_unavailable_context_guard_never_reaches_dispatch_entry() -> None:
    run = _authorized_run()
    run.test_context_guard = DispatchBinding(
        target_ref=run.resource_id,
        access_scope_digest="a" * 64,
        signal_code="test.signal",
        context_digest="sha256:" + "b" * 64,
    )
    executor = AsyncMock(return_value=True)
    await execute(Thor(executor=executor, clock=lambda: NOW), run)
    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "test_context_changed_before_dispatch"
    executor.assert_not_awaited()


@pytest.mark.parametrize("failure", ["timeout", "error", "identity"])
async def test_failed_preflight_never_reaches_dispatch_entry(failure: str) -> None:
    run = _authorized_run()
    run.preflight_required = True
    simulator = AsyncMock()

    async def simulate(snapshot: ActionRun) -> PreflightSimulationResult:
        assert snapshot is not run
        if failure == "timeout":
            raise TimeoutError
        if failure == "error":
            raise RuntimeError("simulator")
        run.params = {"changed": True}
        return PreflightSimulationResult("passed", "test-simulator", "1")

    simulator.simulate.side_effect = simulate
    executor = AsyncMock(return_value=True)
    await execute(Thor(executor=executor, preflight_simulator=simulator, clock=lambda: NOW), run)
    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == ("preflight_timeout" if failure == "timeout" else "preflight_error")
    executor.assert_not_awaited()


@pytest.mark.parametrize("missing", ["resource", "lock"])
async def test_missing_required_execution_identity_or_lock_blocks_dispatch(missing: str) -> None:
    run = _run()
    if missing == "resource":
        run.resource_id = ""
    executor = AsyncMock(return_value=True)
    host = Thor(executor=executor, require_execution_resource_lock=True)
    with pytest.raises((ValueError, RuntimeError)):
        await invoke_executor(host, run)
    executor.assert_not_awaited()


async def test_lock_acquisition_failure_is_retryable_without_dispatch_entry() -> None:
    class Lock:
        @asynccontextmanager
        async def acquire(self, resource_id: str) -> AsyncIterator[None]:
            raise RuntimeError("lock unavailable")
            yield

    run = _authorized_run()
    executor = AsyncMock(return_value=True)
    host = Thor(executor=executor, execution_resource_lock=Lock())
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await execute(host, run)
    assert run.state is ActionRunState.VERDICTED
    assert run.outcome == "execution_resource_temporarily_unavailable"
    executor.assert_not_awaited()
    assert not any(key.startswith("dispatch_start:") for key in host.behavior_snapshot())


@pytest.mark.parametrize("executor_fails", [False, True])
async def test_lock_release_failure_preserves_dispatch_ambiguity(executor_fails: bool) -> None:
    class Lock:
        @asynccontextmanager
        async def acquire(self, resource_id: str) -> AsyncIterator[None]:
            try:
                yield
            finally:
                raise RuntimeError("release unavailable")

    executor = AsyncMock(return_value=True)
    if executor_fails:
        executor.side_effect = RuntimeError("executor unavailable")
    host = Thor(executor=executor, execution_resource_lock=Lock())
    run = _run()
    if executor_fails:
        with pytest.raises(RuntimeError, match="executor unavailable"):
            await invoke_executor(host, run)
    else:
        assert await invoke_executor(host, run)
        assert run.outcome == "command_accepted_lock_release_unknown"
    assert host.behavior_snapshot()["execution_resource_lock:release_unknown"] == 1
    executor.assert_awaited_once()


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("release_fails", [False, True])
async def test_claim_failure_before_observation_cleans_up_lock(
    cancelled: bool, release_fails: bool
) -> None:
    events: list[str] = []

    class Store(_RecordingStore):
        async def refresh_resource_claim(self, run: ActionRun) -> bool:
            if cancelled:
                raise asyncio.CancelledError
            return False

    class Lock:
        @asynccontextmanager
        async def acquire(self, resource_id: str) -> AsyncIterator[None]:
            events.append("acquired")
            try:
                yield
            finally:
                events.append("released")
                if release_fails:
                    raise RuntimeError("release unavailable")

    run = _run()
    run.resource_claimed = True
    store = Store()
    executor = AsyncMock(return_value=True)
    host = Thor(executor=executor, state_store=store, execution_resource_lock=Lock())
    expected = asyncio.CancelledError if cancelled else ExecutionResourceUnavailableError
    with pytest.raises(expected):
        await invoke_executor(host, run)
    assert events == ["acquired", "released"]
    assert store.started_at is None
    executor.assert_not_awaited()
