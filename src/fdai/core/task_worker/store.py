"""Durable lifecycle seam and deterministic in-memory task-worker store."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from fdai.core.task_worker.models import (
    TaskWorkerEvent,
    TaskWorkerResult,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerUsage,
)


class TaskWorkerConflictError(RuntimeError):
    """A worker lifecycle write lost its expected-state race."""


class TaskWorkerStore(Protocol):
    async def create(self, snapshot: TaskWorkerSnapshot) -> tuple[TaskWorkerSnapshot, bool]: ...

    async def get(
        self,
        worker_id: str,
        *,
        owner: str | None = None,
    ) -> TaskWorkerSnapshot | None: ...

    async def transition(
        self,
        worker_id: str,
        *,
        expected: frozenset[TaskWorkerStatus],
        status: TaskWorkerStatus,
        usage: TaskWorkerUsage,
        at: datetime,
        result: TaskWorkerResult | None = None,
    ) -> TaskWorkerSnapshot: ...

    async def heartbeat(
        self,
        worker_id: str,
        *,
        usage: TaskWorkerUsage,
        at: datetime,
    ) -> TaskWorkerSnapshot: ...

    async def append_event(
        self,
        worker_id: str,
        *,
        kind: str,
        at: datetime,
        details: tuple[tuple[str, str], ...] = (),
    ) -> TaskWorkerEvent: ...

    async def list(
        self,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[TaskWorkerSnapshot, ...]: ...

    async def events(
        self,
        worker_id: str,
        *,
        owner: str | None = None,
        limit: int = 500,
    ) -> tuple[TaskWorkerEvent, ...]: ...


class InMemoryTaskWorkerStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, TaskWorkerSnapshot] = {}
        self._events: dict[str, list[TaskWorkerEvent]] = {}
        self._lock = asyncio.Lock()

    async def create(self, snapshot: TaskWorkerSnapshot) -> tuple[TaskWorkerSnapshot, bool]:
        async with self._lock:
            prior = self._snapshots.get(snapshot.request.worker_id)
            if prior is not None:
                if prior.request != snapshot.request:
                    raise TaskWorkerConflictError("worker id reused with another request")
                return prior, False
            self._snapshots[snapshot.request.worker_id] = snapshot
            self._events[snapshot.request.worker_id] = []
            return snapshot, True

    async def get(
        self,
        worker_id: str,
        *,
        owner: str | None = None,
    ) -> TaskWorkerSnapshot | None:
        snapshot = self._snapshots.get(worker_id)
        if snapshot is None or (owner is not None and snapshot.request.cancellation_owner != owner):
            return None
        return snapshot

    async def transition(
        self,
        worker_id: str,
        *,
        expected: frozenset[TaskWorkerStatus],
        status: TaskWorkerStatus,
        usage: TaskWorkerUsage,
        at: datetime,
        result: TaskWorkerResult | None = None,
    ) -> TaskWorkerSnapshot:
        async with self._lock:
            current = self._required(worker_id)
            if current.status not in expected:
                raise TaskWorkerConflictError(
                    f"worker status conflict: expected={sorted(expected)}, current={current.status}"
                )
            updated = replace(
                current,
                status=status,
                usage=usage,
                updated_at=at,
                result=result,
            )
            self._snapshots[worker_id] = updated
            return updated

    async def heartbeat(
        self,
        worker_id: str,
        *,
        usage: TaskWorkerUsage,
        at: datetime,
    ) -> TaskWorkerSnapshot:
        async with self._lock:
            current = self._required(worker_id)
            if current.status is not TaskWorkerStatus.RUNNING:
                return current
            updated = replace(current, usage=usage, heartbeat_at=at, updated_at=at)
            self._snapshots[worker_id] = updated
            return updated

    async def append_event(
        self,
        worker_id: str,
        *,
        kind: str,
        at: datetime,
        details: tuple[tuple[str, str], ...] = (),
    ) -> TaskWorkerEvent:
        async with self._lock:
            self._required(worker_id)
            events = self._events[worker_id]
            event = TaskWorkerEvent(
                worker_id=worker_id,
                sequence=len(events),
                kind=kind,
                at=at,
                details=details,
            )
            events.append(event)
            return event

    async def list(
        self,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[TaskWorkerSnapshot, ...]:
        _limit(limit, 1_000)
        ordered = sorted(
            (
                snapshot
                for snapshot in self._snapshots.values()
                if owner is None or snapshot.request.cancellation_owner == owner
            ),
            key=lambda item: (item.updated_at, item.request.worker_id),
            reverse=True,
        )
        return tuple(ordered[:limit])

    async def events(
        self,
        worker_id: str,
        *,
        owner: str | None = None,
        limit: int = 500,
    ) -> tuple[TaskWorkerEvent, ...]:
        _limit(limit, 5_000)
        snapshot = self._required(worker_id)
        if owner is not None and snapshot.request.cancellation_owner != owner:
            raise LookupError(f"task worker {worker_id!r} was not found")
        return tuple(self._events[worker_id][-limit:])

    def _required(self, worker_id: str) -> TaskWorkerSnapshot:
        try:
            return self._snapshots[worker_id]
        except KeyError as exc:
            raise LookupError(f"task worker {worker_id!r} was not found") from exc


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


__all__ = [
    "InMemoryTaskWorkerStore",
    "TaskWorkerConflictError",
    "TaskWorkerStore",
]
