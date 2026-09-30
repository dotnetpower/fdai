"""Tracked background timeout tasks for Forseti-owned arbitration."""

from __future__ import annotations

import asyncio
from typing import Protocol


class ForsetiTimeoutHost(Protocol):
    _cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]]

    async def _expire_cross_vertical_candidates(self, correlation_id: str) -> None: ...

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


def start_cross_vertical_timeout(host: ForsetiTimeoutHost, correlation_id: str) -> None:
    task = asyncio.create_task(host._expire_cross_vertical_candidates(correlation_id))
    task.add_done_callback(lambda completed: observe_cross_vertical_timeout_task(host, completed))
    host._cross_vertical_timeout_tasks[correlation_id] = task


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
