"""Workflow Process snapshots and append-only transition journal contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

PROCESS_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


class ProcessStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        return self in {
            ProcessStatus.COMPENSATED,
            ProcessStatus.SUCCEEDED,
            ProcessStatus.FAILED,
            ProcessStatus.CANCELLED,
            ProcessStatus.TIMED_OUT,
        }


class ProcessEventKind(StrEnum):
    PROCESS_CREATED = "process.created"
    PROCESS_STARTED = "process.started"
    STEP_STARTED = "step.started"
    STEP_WAITING = "step.waiting"
    EVIDENCE_ATTACHED = "evidence.attached"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RECORDED = "approval.recorded"
    DECISION_RECORDED = "decision.recorded"
    PARALLEL_BRANCH_STARTED = "parallel.branch.started"
    PARALLEL_BRANCH_COMPLETED = "parallel.branch.completed"
    PARALLEL_BRANCH_FAILED = "parallel.branch.failed"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    COMPENSATION_STARTED = "compensation.started"
    COMPENSATION_COMPLETED = "compensation.completed"
    PROCESS_COMPLETED = "process.completed"
    PROCESS_FAILED = "process.failed"
    PROCESS_CANCELLED = "process.cancelled"
    PROCESS_TIMED_OUT = "process.timed_out"


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    process_id: str
    workflow_ref: str
    workflow_version: str
    status: ProcessStatus
    current_step: str
    target_resource_id: str
    started_at: datetime
    updated_at: datetime
    correlation_id: str
    revision: int = 0

    def __post_init__(self) -> None:
        for field_name, value in (
            ("process_id", self.process_id),
            ("workflow_ref", self.workflow_ref),
            ("workflow_version", self.workflow_version),
            ("target_resource_id", self.target_resource_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ValueError(f"ProcessSnapshot.{field_name} MUST be non-empty")
        if not PROCESS_ID_PATTERN.fullmatch(self.process_id):
            raise ValueError(
                "ProcessSnapshot.process_id MUST contain 1-200 URL-safe characters "
                "(letters, digits, underscore, period, colon, or hyphen)"
            )
        if self.started_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("ProcessSnapshot timestamps MUST be timezone-aware")
        if self.revision < 0:
            raise ValueError("ProcessSnapshot.revision MUST be >= 0")


@dataclass(frozen=True, slots=True)
class ProcessEvent:
    event_id: str
    process_id: str
    kind: ProcessEventKind
    idempotency_key: str
    recorded_at: datetime
    correlation_id: str
    causation_id: str | None = None
    step_id: str | None = None
    attempt: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("event_id", self.event_id),
            ("process_id", self.process_id),
            ("idempotency_key", self.idempotency_key),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ValueError(f"ProcessEvent.{field_name} MUST be non-empty")
        if not PROCESS_ID_PATTERN.fullmatch(self.process_id):
            raise ValueError(
                "ProcessEvent.process_id MUST contain 1-200 URL-safe characters "
                "(letters, digits, underscore, period, colon, or hyphen)"
            )
        if self.recorded_at.tzinfo is None:
            raise ValueError("ProcessEvent.recorded_at MUST be timezone-aware")
        if self.attempt < 1:
            raise ValueError("ProcessEvent.attempt MUST be >= 1")


class ProcessRuntimeError(RuntimeError):
    """Base failure for process snapshot and journal operations."""


class ProcessRevisionConflictError(ProcessRuntimeError):
    """Optimistic process update observed a different revision."""


@runtime_checkable
class ProcessRuntimeStore(Protocol):
    """Atomically update the current snapshot and append its transition event."""

    async def create(
        self,
        *,
        snapshot: ProcessSnapshot,
        event: ProcessEvent,
    ) -> tuple[ProcessSnapshot, bool]:
        """Create a process once; return ``(existing, False)`` on re-delivery."""
        ...

    async def transition(
        self,
        *,
        process_id: str,
        expected_revision: int,
        status: ProcessStatus,
        current_step: str,
        event: ProcessEvent,
    ) -> ProcessSnapshot:
        """Append ``event`` and advance the snapshot in one transaction."""
        ...

    async def get(self, process_id: str) -> ProcessSnapshot | None:
        """Return the current process snapshot."""
        ...

    async def events(self, process_id: str) -> tuple[ProcessEvent, ...]:
        """Return the process journal in append order."""
        ...

    async def append_event(self, event: ProcessEvent) -> bool:
        """Append a child event without changing the Process snapshot.

        Return ``False`` when the idempotency key was already recorded for
        this Process. A key owned by another Process is an error.
        """
        ...

    async def list(
        self,
        *,
        workflow_ref: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 100,
    ) -> tuple[ProcessSnapshot, ...]:
        """Return bounded current snapshots, newest-updated first."""
        ...


__all__ = [
    "ProcessEvent",
    "ProcessEventKind",
    "PROCESS_ID_PATTERN",
    "ProcessRevisionConflictError",
    "ProcessRuntimeError",
    "ProcessRuntimeStore",
    "ProcessSnapshot",
    "ProcessStatus",
]
