"""Scheduled task model - a recurring monitoring job.

Design contract: ``docs/roadmap/app-shape.instructions.md`` (Container Apps
Jobs for out-of-band probes) and the Azure SRE Agent parity note in
``docs/internals/sre-agent-gap-analysis.md`` (P2-6). A ``ScheduledTask`` is
an operator-created recurring job that, when due, re-emits a synthetic
event into the standard control loop - detection, trust-router, and
risk-gate stay the sole authority for anything autonomous. The scheduler
never acts directly; it only injects an event.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    """One recurring job definition.

    Immutable - a run advances ``last_run`` by producing a copy via
    :meth:`with_last_run`, so the store swaps the whole record and never
    mutates in place.
    """

    task_id: str
    name: str
    interval_seconds: float
    event_type: str
    created_by: str
    """Entra OID / principal that created the task - recorded for audit and
    RBAC scoping; a task is never anonymous."""

    event_payload: Mapping[str, object] = field(default_factory=dict)
    resource_ref: str | None = None
    enabled: bool = True
    start_at: datetime | None = None
    last_run: datetime | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("ScheduledTask.interval_seconds MUST be positive")
        if not self.task_id:
            raise ValueError("ScheduledTask.task_id MUST be non-empty")
        if not self.created_by:
            raise ValueError("ScheduledTask.created_by MUST be non-empty")

    def with_last_run(self, at: datetime) -> ScheduledTask:
        """Return a copy with ``last_run`` advanced to ``at``."""
        return replace(self, last_run=at)


__all__ = ["ScheduledTask"]
