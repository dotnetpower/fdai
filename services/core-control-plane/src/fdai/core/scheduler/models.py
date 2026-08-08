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
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledResultOrigin,
)


class ScheduleKind(StrEnum):
    INTERVAL = "interval"
    ONE_SHOT = "one-shot"
    CRON = "cron"
    EVENT_EXIT = "event-exit"


@dataclass(frozen=True, slots=True)
class ScheduledRunIsolationProfile:
    """Bound one scheduled session's context, tools, duration, and command sandbox."""

    profile_id: str = "scheduled.default-deny"
    max_session_seconds: int = 300
    max_context_chars: int = 16_000
    max_tool_calls: int = 0
    allowed_tool_ids: frozenset[str] = frozenset()
    command_sandbox_profile_id: str | None = None

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("scheduled isolation profile_id MUST be non-empty")
        if not 1 <= self.max_session_seconds <= 3600:
            raise ValueError("scheduled isolation max_session_seconds MUST be in [1, 3600]")
        if not 1 <= self.max_context_chars <= 1_000_000:
            raise ValueError("scheduled isolation max_context_chars MUST be in [1, 1000000]")
        if not 0 <= self.max_tool_calls <= 100:
            raise ValueError("scheduled isolation max_tool_calls MUST be in [0, 100]")
        if self.max_tool_calls == 0 and self.allowed_tool_ids:
            raise ValueError("scheduled isolation with zero tool calls MUST allow no tools")
        if self.max_tool_calls > 0 and not self.allowed_tool_ids:
            raise ValueError("scheduled isolation tool calls require an explicit tool allowlist")


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
    cron_expression: str | None = None
    schedule_kind: ScheduleKind | None = None
    timezone: str = "UTC"
    exit_event_type: str | None = None
    exit_observed_at: datetime | None = None
    isolation_profile: ScheduledRunIsolationProfile = field(
        default_factory=ScheduledRunIsolationProfile
    )
    continuation_mode: ContinuationMode = ContinuationMode.NONE
    continuation_origin: ScheduledResultOrigin | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("ScheduledTask.interval_seconds MUST be positive")
        if not self.task_id:
            raise ValueError("ScheduledTask.task_id MUST be non-empty")
        if not self.created_by:
            raise ValueError("ScheduledTask.created_by MUST be non-empty")
        effective_kind = self.kind
        if effective_kind is ScheduleKind.CRON:
            if self.cron_expression is None:
                raise ValueError("cron schedule requires cron_expression")
            if len(self.cron_expression.split()) != 5 or not croniter.is_valid(
                self.cron_expression,
                strict=True,
            ):
                raise ValueError("ScheduledTask.cron_expression MUST be a strict 5-field cron")
        elif self.cron_expression is not None:
            raise ValueError("cron_expression requires cron schedule kind")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("ScheduledTask.timezone MUST be a valid IANA timezone") from exc
        if effective_kind is ScheduleKind.ONE_SHOT and self.start_at is None:
            raise ValueError("one-shot schedule requires start_at")
        if effective_kind is ScheduleKind.EVENT_EXIT and not self.exit_event_type:
            raise ValueError("event-exit schedule requires exit_event_type")
        if effective_kind is not ScheduleKind.EVENT_EXIT and (
            self.exit_event_type is not None or self.exit_observed_at is not None
        ):
            raise ValueError("exit fields require event-exit schedule kind")
        if self.continuation_mode is ContinuationMode.NONE:
            if self.continuation_origin is not None:
                raise ValueError("continuation origin requires an enabled continuation mode")
        elif self.continuation_origin is None:
            raise ValueError("enabled continuation requires immutable origin metadata")

    @property
    def kind(self) -> ScheduleKind:
        if self.schedule_kind is not None:
            return self.schedule_kind
        return ScheduleKind.CRON if self.cron_expression is not None else ScheduleKind.INTERVAL

    def with_last_run(self, at: datetime) -> ScheduledTask:
        """Return a copy with ``last_run`` advanced to ``at``."""
        return replace(self, last_run=at)

    def with_exit_observed(self, at: datetime) -> ScheduledTask:
        if self.kind is not ScheduleKind.EVENT_EXIT:
            raise ValueError("only event-exit schedules can observe an exit event")
        return replace(self, exit_observed_at=at, enabled=False)


__all__ = ["ScheduleKind", "ScheduledRunIsolationProfile", "ScheduledTask"]
