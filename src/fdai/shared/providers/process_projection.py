"""Durable retry queue for Process ontology projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.shared.providers.process_runtime import ProcessEvent


@dataclass(frozen=True, slots=True)
class ProcessProjectionJob:
    event: ProcessEvent
    attempts: int
    available_at: datetime
    leased_until: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.attempts < 0:
            raise ValueError("ProcessProjectionJob.attempts MUST be >= 0")
        if self.available_at.tzinfo is None:
            raise ValueError("ProcessProjectionJob.available_at MUST be timezone-aware")
        if self.leased_until is not None and self.leased_until.tzinfo is None:
            raise ValueError("ProcessProjectionJob.leased_until MUST be timezone-aware")


@runtime_checkable
class ProcessProjectionOutbox(Protocol):
    """Queue written atomically with the authoritative Process journal.

    The runtime adapter that implements this protocol MUST enqueue one job in
    the same transaction that appends each new ``ProcessEvent``.
    """

    async def claim_projections(
        self,
        *,
        now: datetime,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> tuple[ProcessProjectionJob, ...]:
        """Lease bounded available jobs for one retry worker."""
        ...

    async def complete_projection(self, event_id: str) -> None:
        """Remove a successfully projected event from the queue."""
        ...

    async def retry_projection(
        self,
        event_id: str,
        *,
        available_at: datetime,
        last_error: str,
    ) -> None:
        """Release a failed job for a later bounded retry."""
        ...


__all__ = ["ProcessProjectionJob", "ProcessProjectionOutbox"]
