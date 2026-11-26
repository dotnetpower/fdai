"""Correlation-local async locks for Thor helpers."""

from __future__ import annotations

import asyncio
from typing import Any


class _ReentrantAsyncLock:
    """Serialize a correlation while allowing synchronous bus callbacks in one task."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def __aenter__(self) -> None:
        current = asyncio.current_task()
        if current is not None and current is self._owner:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = current
        self._depth = 1

    async def __aexit__(self, *_args: object) -> None:
        if asyncio.current_task() is not self._owner:
            raise RuntimeError("correlation lock released by a non-owner task")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


__all__ = ["_ReentrantAsyncLock"]
