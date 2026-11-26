"""Cancellation, scope and failure isolation for one tick's shared Pod reads."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fdai.delivery.pod_tick_cache import PodTickCache


async def test_cancelled_waiter_cannot_cancel_another_pods_shared_read() -> None:
    cache = PodTickCache(timeout_seconds=1)
    started, release = asyncio.Event(), asyncio.Event()

    async def load() -> str:
        started.set()
        await release.wait()
        return "complete-snapshot"

    loader = AsyncMock(side_effect=load)
    first = asyncio.create_task(cache.read(("generation-example", "cluster-example"), loader))
    await started.wait()
    second = asyncio.create_task(cache.read(("generation-example", "cluster-example"), loader))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == "complete-snapshot"
    loader.assert_awaited_once()
    await cache.aclose()


async def test_exact_cluster_and_generation_keys_do_not_alias() -> None:
    cache = PodTickCache(timeout_seconds=1)
    loader = AsyncMock(side_effect=["first-generation", "next-generation", "other-cluster"])
    assert await cache.read(("generation-one", "cluster-one"), loader) == "first-generation"
    assert await cache.read(("generation-two", "cluster-one"), loader) == "next-generation"
    assert await cache.read(("generation-one", "cluster-two"), loader) == "other-cluster"
    assert await cache.read(("generation-one", "cluster-one"), loader) == "first-generation"
    assert loader.await_count == 3
    await cache.aclose()
