"""Backpressure - bounded concurrency with load shedding.

An event storm can drive unbounded concurrent work: every in-flight task
holds memory and a downstream connection, and an unbounded wait queue
just defers the collapse. This primitive bounds concurrency with a
semaphore and *sheds* (rejects fast) once both the in-flight slots and a
bounded wait queue are full, so overload degrades predictably instead of
exhausting the process. Shedding is fail-safe: a shed unit is not
dropped silently - the caller re-queues it to the broker (at-least-once)
or routes it to the DLQ.

Pure asyncio, no I/O. A composition root wraps a hot-path stage's work in
:meth:`Backpressure.slot`; ``core`` stays unaware of the concrete wiring.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


class LoadShedError(RuntimeError):
    """Raised by :meth:`Backpressure.slot` when the system is saturated."""


@dataclass(frozen=True, slots=True)
class BackpressureConfig:
    max_concurrency: int = 32
    """Maximum units executing at once."""

    max_queued: int = 128
    """Waiters allowed to queue for a slot before new arrivals are shed."""

    acquire_timeout_s: float | None = None
    """Optional bound on how long a queued waiter parks for a slot. When
    set, a waiter that is not admitted within the timeout sheds (raises
    :class:`LoadShedError`) instead of blocking forever behind a hung
    in-flight unit. ``None`` waits indefinitely (the semaphore's default)."""

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency MUST be >= 1")
        if self.max_queued < 0:
            raise ValueError("max_queued MUST be >= 0")
        if self.acquire_timeout_s is not None and self.acquire_timeout_s <= 0:
            raise ValueError("acquire_timeout_s MUST be > 0 when set")


@dataclass
class Backpressure:
    """Bounded-concurrency gate that sheds load when saturated."""

    config: BackpressureConfig = field(default_factory=BackpressureConfig)
    _sem: asyncio.Semaphore = field(init=False)
    _in_flight: int = field(default=0, init=False)
    _waiting: int = field(default=0, init=False)
    shed_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(self.config.max_concurrency)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Acquire an execution slot or raise :class:`LoadShedError`.

        Sheds when every slot is in flight AND the wait queue is full, so
        the number of parked coroutines can never exceed
        ``max_concurrency + max_queued``.
        """
        if (
            self._in_flight >= self.config.max_concurrency
            and self._waiting >= self.config.max_queued
        ):
            self.shed_count += 1
            raise LoadShedError(f"saturated: {self._in_flight} in-flight, {self._waiting} queued")
        self._waiting += 1
        try:
            timeout = self.config.acquire_timeout_s
            if timeout is not None:
                try:
                    await asyncio.wait_for(self._sem.acquire(), timeout=timeout)
                except TimeoutError:
                    self.shed_count += 1
                    raise LoadShedError(
                        f"slot acquire timed out after {timeout}s "
                        f"({self._in_flight} in-flight, {self._waiting} queued)"
                    ) from None
            else:
                await self._sem.acquire()
        finally:
            self._waiting -= 1
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1
            self._sem.release()

    def snapshot(self) -> dict[str, int]:
        return {
            "in_flight": self._in_flight,
            "waiting": self._waiting,
            "shed_count": self.shed_count,
            "max_concurrency": self.config.max_concurrency,
            "max_queued": self.config.max_queued,
        }


__all__ = ["Backpressure", "BackpressureConfig", "LoadShedError"]
