"""Schedule store - the shared source of truth for scheduled tasks.

The operator console (create / list / cancel) and the
:class:`~fdai.core.scheduler.service.SchedulerService` (due lookup, run
marking) share one store, so a task created from chat is picked up by the
next scheduler tick. The upstream default :class:`InMemoryScheduleStore`
is process-local; a fork binds a Postgres-backed store at the composition
root so schedules survive a restart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.scheduler.models import ScheduledTask


class ScheduleNotFoundError(KeyError):
    """Raised when a task id is not in the store."""


@runtime_checkable
class ScheduleStore(Protocol):
    """Async CRUD for scheduled tasks."""

    async def create(self, task: ScheduledTask) -> ScheduledTask: ...

    async def get(self, task_id: str) -> ScheduledTask: ...

    async def list_all(self) -> Sequence[ScheduledTask]: ...

    async def update(self, task: ScheduledTask) -> ScheduledTask: ...

    async def cancel(self, task_id: str) -> None: ...

    async def mark_run(self, task_id: str, at: datetime) -> ScheduledTask: ...

    async def mark_exit_event(self, event_type: str, at: datetime) -> int: ...


class InMemoryScheduleStore:
    """Process-local schedule store - the upstream default."""

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}

    async def create(self, task: ScheduledTask) -> ScheduledTask:
        if task.task_id in self._tasks:
            raise ValueError(f"duplicate task_id {task.task_id!r}")
        self._tasks[task.task_id] = task
        return task

    async def get(self, task_id: str) -> ScheduledTask:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise ScheduleNotFoundError(task_id) from exc

    async def list_all(self) -> Sequence[ScheduledTask]:
        return tuple(self._tasks.values())

    async def update(self, task: ScheduledTask) -> ScheduledTask:
        if task.task_id not in self._tasks:
            raise ScheduleNotFoundError(task.task_id)
        self._tasks[task.task_id] = task
        return task

    async def cancel(self, task_id: str) -> None:
        if task_id not in self._tasks:
            raise ScheduleNotFoundError(task_id)
        del self._tasks[task_id]

    async def mark_run(self, task_id: str, at: datetime) -> ScheduledTask:
        task = await self.get(task_id)
        updated = task.with_last_run(at)
        self._tasks[task_id] = updated
        return updated

    async def mark_exit_event(self, event_type: str, at: datetime) -> int:
        matched = 0
        for task_id, task in tuple(self._tasks.items()):
            if task.enabled and task.exit_event_type == event_type:
                self._tasks[task_id] = task.with_exit_observed(at)
                matched += 1
        return matched


__all__ = [
    "InMemoryScheduleStore",
    "ScheduleNotFoundError",
    "ScheduleStore",
]
