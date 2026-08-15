"""Every event-bus consumer must close its subscription inside its own task.

A plain ``async for`` leaves the provider generator open when the frame
unwinds, which defers broker teardown to interpreter finalization - after
asyncio has cancelled the client's internal tasks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.registry import load_pantheon
from fdai.shared.providers.event_bus import EventEnvelope, subscription
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


class _TrackingEventBus(InMemoryEventBus):
    """In-memory bus whose subscriptions record their own close."""

    def __init__(self) -> None:
        super().__init__()
        self.closed = 0
        self.opened = 0

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        inner = super().subscribe(topic, group_id)
        self.opened += 1

        async def _tracked() -> AsyncIterator[EventEnvelope]:
            try:
                async for envelope in inner:
                    yield envelope
                # Idle forever so cancellation, not exhaustion, ends the loop.
                await asyncio.Event().wait()
            finally:
                self.closed += 1

        return _tracked()


async def test_subscription_closes_stream_on_normal_exit() -> None:
    bus = _TrackingEventBus()
    await bus.publish("object.event", "k", {"n": 1})

    async with subscription(bus, "object.event", "group") as stream:
        await anext(stream)

    assert bus.closed == 1


async def test_subscription_closes_stream_on_cancellation() -> None:
    bus = _TrackingEventBus()
    entered = asyncio.Event()

    async def consume() -> None:
        async with subscription(bus, "object.event", "group") as stream:
            entered.set()
            async for _envelope in stream:
                pass

    task = asyncio.create_task(consume())
    await entered.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert bus.closed == 1


async def test_pantheon_bridge_closes_subscription_on_stop() -> None:
    bus = _TrackingEventBus()
    bridge = EventBusBridge(provider=bus, registry=load_pantheon())

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        return None

    bridge.subscribe("object.verdict", "Thor", handler)
    runner = asyncio.create_task(bridge.run())
    async with asyncio.timeout(5):
        while bus.opened == 0:
            await asyncio.sleep(0)
    await bridge.stop()
    await runner

    assert bus.opened >= 1
    assert bus.closed == bus.opened
