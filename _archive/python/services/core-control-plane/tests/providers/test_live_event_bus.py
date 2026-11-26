"""Long-running in-memory EventBus behavior."""

from __future__ import annotations

import asyncio

from fdai.shared.providers.testing import LiveInMemoryEventBus


async def test_waiting_consumer_receives_future_publish() -> None:
    bus = LiveInMemoryEventBus()
    iterator = bus.subscribe("events", "group-1")
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)

    await bus.publish("events", "resource-1", {"value": 1})
    envelope = await asyncio.wait_for(pending, timeout=1.0)

    assert envelope.key == "resource-1"
    assert envelope.payload == {"value": 1}
    await iterator.aclose()


async def test_consumer_groups_replay_independently_and_keep_polling() -> None:
    bus = LiveInMemoryEventBus()
    await bus.publish("events", "r1", {"value": 1})
    await bus.publish("events", "r2", {"value": 2})

    first = bus.subscribe("events", "group-1")
    assert (await anext(first)).payload["value"] == 1
    assert (await anext(first)).payload["value"] == 2

    replay = bus.subscribe("events", "group-2")
    assert (await anext(replay)).payload["value"] == 1
    await replay.aclose()

    pending = asyncio.create_task(anext(first))
    await asyncio.sleep(0)
    await bus.publish("events", "r3", {"value": 3})
    assert (await asyncio.wait_for(pending, timeout=1.0)).payload["value"] == 3
    await first.aclose()
