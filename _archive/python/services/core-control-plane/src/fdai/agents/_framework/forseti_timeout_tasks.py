"""Tracked background timeout tasks for Forseti-owned arbitration."""

from __future__ import annotations

import asyncio
import heapq
from typing import Protocol

_SCHEDULER_KEY = "__cross_vertical_timeout_scheduler__"


class ForsetiTimeoutHost(Protocol):
    _cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]]
    _cross_vertical_timeout_deadlines: dict[str, float]
    _cross_vertical_timeout_heap: list[tuple[float, str]]
    _cross_vertical_timeout_seconds: float
    _cross_vertical_timeout_max: int

    async def _expire_cross_vertical_candidates(self, correlation_id: str) -> None: ...

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


def start_cross_vertical_timeout(
    host: ForsetiTimeoutHost,
    correlation_id: str,
    *,
    delay_seconds: float | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    delay = host._cross_vertical_timeout_seconds if delay_seconds is None else delay_seconds
    deadline = loop.time() + max(delay, 0.0)
    previous_earliest = (
        min(host._cross_vertical_timeout_deadlines.values())
        if host._cross_vertical_timeout_deadlines
        else None
    )
    host._cross_vertical_timeout_deadlines[correlation_id] = deadline
    heapq.heappush(host._cross_vertical_timeout_heap, (deadline, correlation_id))
    while len(host._cross_vertical_timeout_deadlines) > host._cross_vertical_timeout_max:
        oldest = next(iter(host._cross_vertical_timeout_deadlines))
        host._cross_vertical_timeout_deadlines.pop(oldest, None)
    task = host._cross_vertical_timeout_tasks.get(_SCHEDULER_KEY)
    if task is None or task.done() or previous_earliest is None or deadline < previous_earliest:
        _ensure_timeout_scheduler(host)


def _ensure_timeout_scheduler(host: ForsetiTimeoutHost) -> None:
    task = host._cross_vertical_timeout_tasks.get(_SCHEDULER_KEY)
    if task is not None and not task.done():
        task.cancel()
    task = asyncio.create_task(_run_timeout_scheduler(host))
    task.add_done_callback(lambda completed: observe_cross_vertical_timeout_task(host, completed))
    host._cross_vertical_timeout_tasks[_SCHEDULER_KEY] = task


async def _run_timeout_scheduler(host: ForsetiTimeoutHost) -> None:
    try:
        while host._cross_vertical_timeout_heap:
            deadline, correlation_id = heapq.heappop(host._cross_vertical_timeout_heap)
            current = host._cross_vertical_timeout_deadlines.get(correlation_id)
            if current != deadline:
                continue
            delay = deadline - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
            if host._cross_vertical_timeout_deadlines.pop(correlation_id, None) == deadline:
                await host._expire_cross_vertical_candidates(correlation_id)
    finally:
        host._cross_vertical_timeout_tasks.pop(_SCHEDULER_KEY, None)


def observe_cross_vertical_timeout_task(
    host: ForsetiTimeoutHost,
    task: asyncio.Task[None],
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001 - background timeout failures are safety signals
        host.record_behavior("cross_vertical_timeout:failed")


async def cancel_cross_vertical_timeout(task: asyncio.Task[None]) -> None:
    if task is asyncio.current_task():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
