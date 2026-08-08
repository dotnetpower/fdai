"""Concurrency contracts for the process-local EventBus adapter."""

from __future__ import annotations

import asyncio

from fdai.shared.providers.local import LocalEventBus


async def test_same_group_never_leases_one_offset_to_concurrent_consumers() -> None:
    bus = LocalEventBus()
    await bus.publish("object.event", "resource-1", {"sequence": 1})

    first = bus.subscribe("object.event", "agent-group")
    second = bus.subscribe("object.event", "agent-group")
    first_message = await anext(first)
    second_next = asyncio.create_task(anext(second))

    await asyncio.sleep(0)
    leased_concurrently = second_next.done()
    await first.aclose()
    redelivered = await asyncio.wait_for(second_next, timeout=0.5)
    await second.aclose()

    assert leased_concurrently is False
    assert first_message.offset == redelivered.offset == 0


async def test_unacknowledged_group_does_not_block_publish_or_another_group() -> None:
    bus = LocalEventBus()
    await bus.publish("object.event", "resource-1", {"sequence": 1})

    slow_group = bus.subscribe("object.event", "slow-agent")
    independent_group = bus.subscribe("object.event", "independent-agent")
    slow_message = await anext(slow_group)

    receipt = await asyncio.wait_for(
        bus.publish("object.event", "resource-2", {"sequence": 2}),
        timeout=0.5,
    )
    independent_message = await asyncio.wait_for(anext(independent_group), timeout=0.5)
    await slow_group.aclose()
    await independent_group.aclose()

    assert slow_message.offset == independent_message.offset == 0
    assert receipt.offset == 1
