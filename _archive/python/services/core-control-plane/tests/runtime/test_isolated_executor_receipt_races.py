"""Late receipt intake preserves its durable wakeup under retirement and backpressure."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.isolated_executor_receipt_journal import BoundExecutorReceiptJournal
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import Mode, SafeguardBoundExecutorCommand
from fdai.shared.providers.executor_receipt_journal import ExecutorReceiptStorageUnavailableError
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.executor.test_direct_api_executor import _action
from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator
from tests.runtime.test_isolated_executor_receipt_journal import (
    _PREFIX,
    _bind_journal,
    _command,
    _receipt,
)


async def _pending_command() -> tuple[
    InMemoryStateStore, InMemoryEventBus, PostReleaseClosureStore, SafeguardBoundExecutorCommand
]:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    closures = coordinator._closure._closure_store
    client = EventBusDirectApiExecutionClient(bus, store, "core-receipt-race")
    _bind_journal(client, closures)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
        command = await _command(bus)
    finally:
        await client.stop()
    return store, bus, closures, command


async def test_timeout_retirement_cannot_erase_a_concurrent_late_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, bus, closures, command = await _pending_command()
    journal = BoundExecutorReceiptJournal(
        store,
        capacity=1,
        closure_store=closures,
        clock=lambda: command.deadline_at + timedelta(seconds=31),
    )
    absent = asyncio.Event()
    resume = asyncio.Event()
    original_read = store.read_state
    receipt_key = f"{_PREFIX}terminal-receipt:{command.command_id}"

    async def pause_absence(key: str) -> Mapping[str, Any] | None:
        value = await original_read(key)
        if key == receipt_key and value is None and not absent.is_set():
            absent.set()
            await resume.wait()
        return value

    monkeypatch.setattr(store, "read_state", pause_absence)
    retirement = asyncio.create_task(journal.reconcile())
    try:
        await asyncio.wait_for(absent.wait(), timeout=2)
        assert await journal.accept(_receipt(command), partition_key=command.partition_key)
    finally:
        resume.set()
    assert await retirement == 0

    restarted = BoundExecutorReceiptJournal(store, capacity=1, closure_store=closures)
    assert await restarted.reconcile() == 1
    result = await store.read_state(f"{_PREFIX}receipt-reconciliation:{command.command_id}")
    assert result is not None
    assert result["effect_verified"] is False
    assert await _command(bus, group="test-race-no-republication") == command


async def test_late_receipt_capacity_exhaustion_is_recoverable_backpressure() -> None:
    store, bus, closures, command = await _pending_command()
    journal = BoundExecutorReceiptJournal(
        store,
        capacity=1,
        closure_store=closures,
        clock=lambda: command.deadline_at + timedelta(seconds=31),
    )
    assert await journal.reconcile() == 1
    occupied = UUID(int=301)
    await journal._change_work(occupied, add=True)
    receipt = _receipt(command)

    with pytest.raises(ExecutorReceiptStorageUnavailableError, match="capacity"):
        await journal.accept(receipt, partition_key=command.partition_key)
    assert await store.read_state(
        f"{_PREFIX}terminal-receipt:{command.command_id}"
    ) == receipt.model_dump(mode="json")

    await journal._change_work(occupied, add=False)
    assert await journal.accept(receipt, partition_key=command.partition_key)
    assert await journal.reconcile() == 1
    assert await _command(bus, group="test-backpressure-no-republication") == command
