"""Dispatch run ledger for reliable scheduled-event publication."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ScheduleDispatchStatus(StrEnum):
    CLAIMED = "claimed"
    PUBLISHED = "published"
    FAILED = "failed"
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class ScheduleDispatchRun:
    """One durable attempt to publish a scheduled event."""

    run_id: str
    task_id: str
    scheduled_for: datetime
    claimed_at: datetime
    status: ScheduleDispatchStatus = ScheduleDispatchStatus.CLAIMED
    attempt: int = 1
    completed_at: datetime | None = None
    error_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.task_id:
            raise ValueError("schedule dispatch run ids MUST be non-empty")
        if self.attempt < 1:
            raise ValueError("schedule dispatch attempt MUST be positive")


@runtime_checkable
class ScheduleRunLedger(Protocol):
    """Atomic claim and terminal history for scheduler dispatches."""

    async def claim(self, run: ScheduleDispatchRun) -> bool: ...

    async def complete(
        self,
        run_id: str,
        *,
        status: ScheduleDispatchStatus,
        at: datetime,
        error_kind: str | None = None,
    ) -> ScheduleDispatchRun: ...

    async def list_for_task(self, task_id: str) -> Sequence[ScheduleDispatchRun]: ...

    async def reconcile_stale(
        self,
        *,
        before: datetime,
        at: datetime,
    ) -> Sequence[ScheduleDispatchRun]: ...


class InMemoryScheduleRunLedger:
    """Process-local implementation with production-equivalent transitions."""

    def __init__(self) -> None:
        self._runs: dict[str, ScheduleDispatchRun] = {}

    async def claim(self, run: ScheduleDispatchRun) -> bool:
        current = self._runs.get(run.run_id)
        if current is None:
            self._runs[run.run_id] = run
            return True
        if current.status not in {ScheduleDispatchStatus.FAILED, ScheduleDispatchStatus.LOST}:
            return False
        self._runs[run.run_id] = replace(
            run,
            attempt=current.attempt + 1,
        )
        return True

    async def complete(
        self,
        run_id: str,
        *,
        status: ScheduleDispatchStatus,
        at: datetime,
        error_kind: str | None = None,
    ) -> ScheduleDispatchRun:
        if status not in {ScheduleDispatchStatus.PUBLISHED, ScheduleDispatchStatus.FAILED}:
            raise ValueError("schedule dispatch completion MUST be published or failed")
        current = self._runs[run_id]
        if current.status is not ScheduleDispatchStatus.CLAIMED:
            raise ValueError("only a claimed schedule dispatch can complete")
        updated = replace(
            current,
            status=status,
            completed_at=at,
            error_kind=error_kind,
        )
        self._runs[run_id] = updated
        return updated

    async def list_for_task(self, task_id: str) -> Sequence[ScheduleDispatchRun]:
        return tuple(run for run in self._runs.values() if run.task_id == task_id)

    async def reconcile_stale(
        self,
        *,
        before: datetime,
        at: datetime,
    ) -> Sequence[ScheduleDispatchRun]:
        reconciled: list[ScheduleDispatchRun] = []
        for run_id, run in tuple(self._runs.items()):
            if run.status is not ScheduleDispatchStatus.CLAIMED or run.claimed_at > before:
                continue
            updated = replace(
                run,
                status=ScheduleDispatchStatus.LOST,
                completed_at=at,
                error_kind="claim_expired",
            )
            self._runs[run_id] = updated
            reconciled.append(updated)
        return tuple(reconciled)


__all__ = [
    "InMemoryScheduleRunLedger",
    "ScheduleDispatchRun",
    "ScheduleDispatchStatus",
    "ScheduleRunLedger",
]
