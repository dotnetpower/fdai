"""Logical-target lock evidence for the isolated Executor shadow runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import pytest

from fdai.core.executor.lock import ResourceLockManager
from fdai.runtime.isolated_executor_lock import LockedIsolatedExecutorShadowService
from fdai.shared.contracts import (
    ExecutorCommand,
    ExecutorShadowReceipt,
    ExecutorShadowReceiptStatus,
)
from fdai.shared.contracts.models import ExecutionPath, Mode

NOW = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)


def _command(*, identity: int, target: str) -> ExecutorCommand:
    action_id = UUID(f"00000000-0000-0000-0000-{identity:012d}")
    event_id = UUID(f"00000000-0000-0000-0001-{identity:012d}")
    payload = {
        "schema_version": "1.0.0",
        "action_id": str(action_id),
        "event_id": str(event_id),
        "idempotency_key": f"isolated-lock-{identity}",
        "target_resource_ref": target,
        "mode": "shadow",
    }
    return ExecutorCommand.model_validate(
        {
            "command_id": UUID(f"00000000-0000-0000-0002-{identity:012d}"),
            "action_schema_version": "1.0.0",
            "action_id": action_id,
            "event_id": event_id,
            "idempotency_key": f"isolated-lock-{identity}",
            "target_resource_ref": target,
            "partition_key": target,
            "execution_path": ExecutionPath.DIRECT_API,
            "requested_mode": Mode.SHADOW,
            "attempt": 1,
            "issued_at": NOW,
            "deadline_at": NOW + timedelta(minutes=1),
            "action_payload_digest": _digest(payload),
            "action_payload": payload,
        }
    )


def _digest(payload: Mapping[str, object]) -> str:
    from fdai.shared.contracts import executor_action_payload_digest

    return executor_action_payload_digest(payload)


def _receipt(command: ExecutorCommand) -> ExecutorShadowReceipt:
    return ExecutorShadowReceipt(
        receipt_id=UUID(f"00000000-0000-0000-0003-{command.action_id.int % 10**12:012d}"),
        command_id=command.command_id,
        action_id=command.action_id,
        idempotency_key=command.idempotency_key,
        attempt=command.attempt,
        action_payload_digest=command.action_payload_digest,
        requested_mode=command.requested_mode,
        status=ExecutorShadowReceiptStatus.SHADOWED,
        reason="shadow command closed while target lock was held",
        executor_instance_id="isolated-executor-lock-test",
        received_at=NOW,
        completed_at=NOW,
        effect_applied=False,
    )


class _BlockingDelegate:
    def __init__(self, expected_entries: int) -> None:
        self.entered: list[str] = []
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()
        self._expected_entries = expected_entries

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt:
        self.entered.append(command.target_resource_ref)
        if len(self.entered) >= self._expected_entries:
            self.all_entered.set()
        await self.release.wait()
        return _receipt(command)


async def test_same_target_commands_are_serialized() -> None:
    delegate = _BlockingDelegate(expected_entries=1)
    service = LockedIsolatedExecutorShadowService(
        delegate=delegate,
        resource_lock=ResourceLockManager(),
    )
    first = asyncio.create_task(service.handle(_command(identity=111, target="resource:one")))
    await delegate.all_entered.wait()
    second = asyncio.create_task(service.handle(_command(identity=112, target="resource:one")))
    await asyncio.sleep(0)

    assert delegate.entered == ["resource:one"]
    delegate.release.set()
    first_receipt, second_receipt = await asyncio.gather(first, second)
    assert first_receipt.effect_applied is second_receipt.effect_applied is False
    assert delegate.entered == ["resource:one", "resource:one"]


async def test_different_targets_can_enter_concurrently() -> None:
    delegate = _BlockingDelegate(expected_entries=2)
    service = LockedIsolatedExecutorShadowService(
        delegate=delegate,
        resource_lock=ResourceLockManager(),
    )
    first = asyncio.create_task(service.handle(_command(identity=113, target="resource:one")))
    second = asyncio.create_task(service.handle(_command(identity=114, target="resource:two")))

    await asyncio.wait_for(delegate.all_entered.wait(), timeout=1)
    assert set(delegate.entered) == {"resource:one", "resource:two"}
    delegate.release.set()
    await asyncio.gather(first, second)


class _FailThenSucceedDelegate:
    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("durable closure unavailable")
        return _receipt(command)


async def test_handler_failure_releases_target_lock() -> None:
    delegate = _FailThenSucceedDelegate()
    lock = ResourceLockManager()
    service = LockedIsolatedExecutorShadowService(delegate=delegate, resource_lock=lock)

    with pytest.raises(RuntimeError, match="closure unavailable"):
        await service.handle(_command(identity=115, target="resource:one"))
    receipt = await service.handle(_command(identity=116, target="resource:one"))

    assert receipt.effect_applied is False
    assert lock.snapshot() == {}


class _RecordingLock:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.held = False

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        self.keys.append(resource_id)
        self.held = True
        try:
            yield
        finally:
            self.held = False


class _LockAssertingDelegate(Protocol):
    lock: _RecordingLock

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt: ...


class _AssertHeldDelegate:
    def __init__(self, lock: _RecordingLock) -> None:
        self.lock = lock

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt:
        assert self.lock.held is True
        return _receipt(command)


async def test_exact_target_lock_is_held_through_terminal_receipt() -> None:
    lock = _RecordingLock()
    delegate: _LockAssertingDelegate = _AssertHeldDelegate(lock)
    service = LockedIsolatedExecutorShadowService(delegate=delegate, resource_lock=lock)
    command = _command(identity=117, target="resource:exact")

    receipt = await service.handle(command)

    assert lock.keys == [command.target_resource_ref]
    assert lock.held is False
    assert receipt.status is ExecutorShadowReceiptStatus.SHADOWED
