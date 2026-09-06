"""Durable terminals wake SSE readers without waiting for their polling interval."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnBridge,
    _SemanticProgressRelay,
)


async def test_terminal_wakes_an_existing_waiter_without_polling_delay() -> None:
    relay = _SemanticProgressRelay()
    waiter = asyncio.create_task(relay.wait_for_update("example-request", 0, timeout=60))
    await asyncio.sleep(0)
    assert not waiter.done()
    relay.terminal_committed("example-request")
    await asyncio.wait_for(waiter, timeout=0.1)
    relay.discard("example-request")
    assert not relay._terminals
    assert not relay._signals


async def test_terminal_before_wait_cannot_be_lost_when_signal_is_cleared() -> None:
    relay = _SemanticProgressRelay()
    relay.terminal_committed("example-request")
    await asyncio.wait_for(relay.wait_for_update("example-request", 0, timeout=60), timeout=0.1)
    assert not relay._signals


def test_terminal_marker_memory_is_bounded() -> None:
    relay = _SemanticProgressRelay()
    for index in range(512):
        relay.terminal_committed(f"request-{index}")
    assert len(relay._terminals) == 256
    assert "request-0" not in relay._terminals
    assert "request-511" in relay._terminals


@pytest.mark.parametrize("reject", [False, True])
async def test_consumer_signals_only_after_persistence_completes(reject: bool) -> None:
    persisted = asyncio.Event()
    started = asyncio.Event()
    finished = asyncio.Event()
    quarantines = []

    class Source:
        async def subscribe(self, topic, group_id):
            yield {}
            finished.set()
            await asyncio.Event().wait()

    class Publisher:
        async def publish(self, topic, key, payload):
            quarantines.append(key)

    class Consumer:
        async def consume(self, payload):
            started.set()
            await persisted.wait()
            if reject:
                raise ValueError("Synthetic invalid terminal")
            return SimpleNamespace(request_id="example-request")

    bridge = SemanticTurnBridge(
        store=SimpleNamespace(),
        publisher=Publisher(),
        result_source=Source(),
    )
    bridge._consumer = Consumer()
    task = asyncio.create_task(bridge._run_result_consumer())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not bridge._progress_relay._terminals
        persisted.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert ("example-request" in bridge._progress_relay._terminals) is not reject
        assert len(quarantines) == int(reject)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
