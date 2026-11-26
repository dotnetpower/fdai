"""Tests for the Backpressure bounded-concurrency gate."""

from __future__ import annotations

import asyncio

import pytest
from fdai.shared.resilience.backpressure import (
    Backpressure,
    BackpressureConfig,
    LoadShedError,
)


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        BackpressureConfig(max_concurrency=0)
    with pytest.raises(ValueError, match="max_queued"):
        BackpressureConfig(max_queued=-1)


async def test_allows_up_to_concurrency() -> None:
    bp = Backpressure(BackpressureConfig(max_concurrency=2, max_queued=4))
    async with bp.slot():
        assert bp.snapshot()["in_flight"] == 1
    assert bp.snapshot()["in_flight"] == 0


async def test_sheds_when_saturated() -> None:
    bp = Backpressure(BackpressureConfig(max_concurrency=1, max_queued=0))
    release = asyncio.Event()

    async def _hold() -> None:
        async with bp.slot():
            await release.wait()

    task = asyncio.create_task(_hold())
    for _ in range(20):  # let it acquire the only slot
        await asyncio.sleep(0)
        if bp.snapshot()["in_flight"] == 1:
            break
    assert bp.snapshot()["in_flight"] == 1

    # Saturated (1 in-flight, 0 queue capacity) -> next arrival is shed.
    with pytest.raises(LoadShedError):
        async with bp.slot():
            pass
    assert bp.shed_count == 1

    release.set()
    await task
    assert bp.snapshot()["in_flight"] == 0


async def test_queued_waiter_admitted_after_release() -> None:
    bp = Backpressure(BackpressureConfig(max_concurrency=1, max_queued=1))
    release = asyncio.Event()
    admitted: list[str] = []

    async def _hold(name: str) -> None:
        async with bp.slot():
            admitted.append(name)
            await release.wait()

    first = asyncio.create_task(_hold("first"))
    for _ in range(20):
        await asyncio.sleep(0)
        if "first" in admitted:
            break

    # Second queues (within max_queued=1), not shed.
    second = asyncio.create_task(_hold("second"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert admitted == ["first"]  # second waiting for the slot

    release.set()
    await asyncio.gather(first, second)
    assert set(admitted) == {"first", "second"}


def test_config_rejects_non_positive_acquire_timeout() -> None:
    with pytest.raises(ValueError, match="acquire_timeout_s"):
        BackpressureConfig(acquire_timeout_s=0)


async def test_acquire_timeout_sheds_instead_of_parking_forever() -> None:
    # H10: a waiter that cannot be admitted within acquire_timeout_s sheds
    # (LoadShedError) rather than blocking forever behind a hung in-flight unit.
    bp = Backpressure(BackpressureConfig(max_concurrency=1, max_queued=8, acquire_timeout_s=0.05))
    release = asyncio.Event()

    async def _hold() -> None:
        async with bp.slot():
            await release.wait()

    holder = asyncio.create_task(_hold())
    for _ in range(50):
        await asyncio.sleep(0)
        if bp.snapshot()["in_flight"] == 1:
            break

    # The single slot is held; a second waiter should time out and shed.
    with pytest.raises(LoadShedError, match="timed out"):
        async with bp.slot():
            pass
    assert bp.snapshot()["shed_count"] == 1
    # The waiter released its queue slot on shed - no leaked waiter.
    assert bp.snapshot()["waiting"] == 0

    release.set()
    await holder
