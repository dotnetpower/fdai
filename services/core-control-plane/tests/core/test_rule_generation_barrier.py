from __future__ import annotations

import asyncio

import pytest
from fdai.core.control_loop._rule_generation import RuleGenerationBarrier


@pytest.mark.asyncio
async def test_rule_generation_barrier_allows_concurrent_readers() -> None:
    barrier = RuleGenerationBarrier()
    active = 0
    peak = 0

    async def read() -> None:
        nonlocal active, peak
        async with barrier.read():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(read(), read())

    assert peak == 2


@pytest.mark.asyncio
async def test_rule_generation_barrier_waits_for_active_reader_before_write() -> None:
    barrier = RuleGenerationBarrier()
    reader_entered = asyncio.Event()
    release_reader = asyncio.Event()
    writer_entered = asyncio.Event()

    async def read() -> None:
        async with barrier.read():
            reader_entered.set()
            await release_reader.wait()

    async def write() -> None:
        async with barrier.write():
            writer_entered.set()

    reader = asyncio.create_task(read())
    await reader_entered.wait()
    writer = asyncio.create_task(write())
    await asyncio.sleep(0)
    assert not writer_entered.is_set()

    release_reader.set()
    await asyncio.gather(reader, writer)

    assert writer_entered.is_set()
