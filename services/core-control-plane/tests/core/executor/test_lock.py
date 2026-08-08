"""ResourceLockManager - per-resource serialization invariants."""

from __future__ import annotations

import asyncio

import pytest
from fdai.core.executor.lock import ResourceLockManager


@pytest.mark.asyncio
async def test_locks_are_created_lazily_per_resource() -> None:
    lock = ResourceLockManager()
    assert lock.snapshot() == {}

    async with lock.acquire("rid-a"):
        assert lock.snapshot() == {"rid-a": True}
    # Refcount hits zero on exit, so the entry is evicted (no unbounded
    # growth over many distinct resource ids).
    assert lock.snapshot() == {}


@pytest.mark.asyncio
async def test_concurrent_actions_on_one_resource_are_serialized() -> None:
    """Two tasks racing on the same resource_id MUST NOT interleave."""
    lock = ResourceLockManager()
    order: list[str] = []

    async def worker(name: str, delay: float) -> None:
        async with lock.acquire("shared"):
            order.append(f"{name}-in")
            await asyncio.sleep(delay)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a", 0.02), worker("b", 0.0))
    # Whichever grabbed the lock first MUST fully exit before the other enters.
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


@pytest.mark.asyncio
async def test_different_resources_run_in_parallel() -> None:
    lock = ResourceLockManager()
    order: list[str] = []

    async def worker(name: str, resource: str) -> None:
        async with lock.acquire(resource):
            order.append(f"{name}-in")
            await asyncio.sleep(0.02)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a", "res-a"), worker("b", "res-b"))
    # Interleaving allowed on distinct resources.
    assert order[0].endswith("-in")
    assert order[1].endswith("-in")


@pytest.mark.asyncio
async def test_snapshot_reflects_current_locked_state() -> None:
    lock = ResourceLockManager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        async with lock.acquire("held"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold())
    await entered.wait()
    assert lock.snapshot() == {"held": True}
    release.set()
    await task
    # Evicted once the holder releases (refcount zero).
    assert lock.snapshot() == {}
