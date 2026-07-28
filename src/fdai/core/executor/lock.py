"""Per-resource lock manager for the executor.

Multiple concurrent events may target the same resource - a rotate-secret
action and a right-size action on the same Container App, say. Applying
them in parallel would violate the ordering rule in
``architecture.instructions.md § Idempotency, Ordering, and Replay``:

> Events that mutate the same resource are serialized on a per-resource
> key; concurrent actions on one resource are mutually excluded.

Design
------

- One :class:`asyncio.Lock` per ``resource_id``, created lazily.
- This implementation stays in-process and is the local/single-replica
    default behind the ``ResourceLock`` seam. Scale-out composition injects
    ``PostgresAdvisoryResourceLock`` for cross-replica exclusion; the event
    bus resource partition key separately preserves per-resource ordering.
- The manager MUST be safe to reuse across concurrent tasks - the
  per-resource-id dictionary itself is guarded by an internal lock.
- Locks are held for the *duration of the action*; short critical
  sections keep the throughput acceptable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class _LockEntry:
    """A per-resource lock plus a refcount of interested callers."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refcount: int = 0


class ResourceLockManager:
    """Serialize actions per-resource in-process.

    Not persistent - a process restart forgets in-flight locks. That is
    acceptable because the audit log records every action; a replayed
    event acquires the lock and dedupes on ``idempotency_key`` before
    doing any work.
    """

    def __init__(self) -> None:
        # resource_id -> (lock, refcount). The refcount tracks how many
        # callers currently hold or are waiting on the lock; the entry is
        # evicted once it drops to zero so the map cannot grow without
        # bound over a long-running process that touches many distinct
        # resource ids (a memory leak otherwise).
        self._locks: dict[str, _LockEntry] = {}
        self._registry_lock = asyncio.Lock()

    async def _checkout(self, resource_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            entry = self._locks.get(resource_id)
            if entry is None:
                entry = _LockEntry()
                self._locks[resource_id] = entry
            entry.refcount += 1
            return entry.lock

    async def _checkin(self, resource_id: str) -> None:
        async with self._registry_lock:
            entry = self._locks.get(resource_id)
            if entry is None:
                return
            entry.refcount -= 1
            if entry.refcount <= 0:
                del self._locks[resource_id]

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        """Hold the lock for ``resource_id`` until the ``async with`` exits."""
        # Reference is counted before the (possibly awaiting) acquire so a
        # concurrent release cannot evict the entry out from under a waiter.
        lock = await self._checkout(resource_id)
        try:
            async with lock:
                yield
        finally:
            await self._checkin(resource_id)

    def snapshot(self) -> dict[str, bool]:
        """Test-only helper: which resource ids are currently locked."""
        return {rid: entry.lock.locked() for rid, entry in self._locks.items()}


__all__ = ["ResourceLockManager"]
