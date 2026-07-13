"""In-memory transactional Process snapshot and journal store."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from fdai.shared.providers.process_projection import ProcessProjectionJob
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessRevisionConflictError,
    ProcessRuntimeError,
    ProcessSnapshot,
    ProcessStatus,
)


class InMemoryProcessRuntimeStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, ProcessSnapshot] = {}
        self._events: dict[str, list[ProcessEvent]] = {}
        self._idempotency: dict[str, ProcessEvent] = {}
        self._projection_jobs: dict[str, ProcessProjectionJob] = {}

    async def create(
        self,
        *,
        snapshot: ProcessSnapshot,
        event: ProcessEvent,
    ) -> tuple[ProcessSnapshot, bool]:
        if snapshot.process_id != event.process_id:
            raise ProcessRuntimeError("snapshot and event process ids MUST match")
        existing = self._snapshots.get(snapshot.process_id)
        if existing is not None:
            return existing, False
        if event.idempotency_key in self._idempotency:
            raise ProcessRuntimeError("process event idempotency key belongs to another process")
        stored = replace(snapshot, revision=1)
        self._snapshots[stored.process_id] = stored
        self._events[stored.process_id] = [event]
        self._idempotency[event.idempotency_key] = event
        self._enqueue_projection(event)
        return stored, True

    async def transition(
        self,
        *,
        process_id: str,
        expected_revision: int,
        status: ProcessStatus,
        current_step: str,
        event: ProcessEvent,
    ) -> ProcessSnapshot:
        existing = self._snapshots.get(process_id)
        if existing is None:
            raise ProcessRuntimeError(f"unknown process {process_id!r}")
        duplicate = self._idempotency.get(event.idempotency_key)
        if duplicate is not None:
            if duplicate.process_id != process_id:
                raise ProcessRuntimeError(
                    "process event idempotency key belongs to another process"
                )
            return existing
        if event.process_id != process_id:
            raise ProcessRuntimeError("transition event process id MUST match")
        if existing.revision != expected_revision:
            raise ProcessRevisionConflictError(
                f"process {process_id!r} revision mismatch: "
                f"expected {expected_revision}, current {existing.revision}"
            )
        stored = replace(
            existing,
            status=status,
            current_step=current_step,
            updated_at=event.recorded_at,
            revision=existing.revision + 1,
        )
        self._snapshots[process_id] = stored
        self._events[process_id].append(event)
        self._idempotency[event.idempotency_key] = event
        self._enqueue_projection(event)
        return stored

    async def get(self, process_id: str) -> ProcessSnapshot | None:
        return self._snapshots.get(process_id)

    async def events(self, process_id: str) -> tuple[ProcessEvent, ...]:
        return tuple(self._events.get(process_id, ()))

    async def append_event(self, event: ProcessEvent) -> bool:
        if event.process_id not in self._snapshots:
            raise ProcessRuntimeError(f"unknown process {event.process_id!r}")
        duplicate = self._idempotency.get(event.idempotency_key)
        if duplicate is not None:
            if duplicate.process_id != event.process_id:
                raise ProcessRuntimeError(
                    "process event idempotency key belongs to another process"
                )
            return False
        self._events[event.process_id].append(event)
        self._idempotency[event.idempotency_key] = event
        self._enqueue_projection(event)
        return True

    async def claim_projections(
        self,
        *,
        now: datetime,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> tuple[ProcessProjectionJob, ...]:
        if now.tzinfo is None:
            raise ValueError("now MUST be timezone-aware")
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        available = [
            job
            for job in self._projection_jobs.values()
            if job.available_at <= now
            and (job.leased_until is None or job.leased_until <= now)
        ]
        available.sort(key=lambda job: (job.available_at, job.event.event_id))
        claimed: list[ProcessProjectionJob] = []
        for job in available[:limit]:
            leased = replace(
                job,
                attempts=job.attempts + 1,
                leased_until=now + timedelta(seconds=lease_seconds),
            )
            self._projection_jobs[job.event.event_id] = leased
            claimed.append(leased)
        return tuple(claimed)

    async def complete_projection(self, event_id: str) -> None:
        self._projection_jobs.pop(event_id, None)

    async def retry_projection(
        self,
        event_id: str,
        *,
        available_at: datetime,
        last_error: str,
    ) -> None:
        job = self._projection_jobs.get(event_id)
        if job is None:
            return
        self._projection_jobs[event_id] = replace(
            job,
            available_at=available_at,
            leased_until=None,
            last_error=last_error,
        )

    async def list(
        self,
        *,
        workflow_ref: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 100,
    ) -> tuple[ProcessSnapshot, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        selected = [
            snapshot
            for snapshot in self._snapshots.values()
            if (workflow_ref is None or snapshot.workflow_ref == workflow_ref)
            and (status is None or snapshot.status is status)
        ]
        selected.sort(key=lambda item: (item.updated_at, item.process_id), reverse=True)
        return tuple(selected[:limit])

    def _enqueue_projection(self, event: ProcessEvent) -> None:
        self._projection_jobs[event.event_id] = ProcessProjectionJob(
            event=event,
            attempts=0,
            available_at=event.recorded_at,
        )


__all__ = ["InMemoryProcessRuntimeStore"]
