"""Per-principal quotas for detached read-only investigations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.background_task.models import (
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskStatus,
)

ACTIVE_BACKGROUND_STATUSES = frozenset(
    {
        BackgroundTaskStatus.QUEUED,
        BackgroundTaskStatus.CLAIMED,
        BackgroundTaskStatus.RUNNING,
    }
)


class BackgroundTaskQuotaExceededError(PermissionError):
    """A principal would exceed a configured read-investigation quota."""


@dataclass(frozen=True, slots=True)
class BackgroundTaskQuotaPolicy:
    max_active_tasks: int = 2
    max_daily_cost_microusd: int = 1_000_000
    max_wall_seconds_per_task: int = 300
    max_tool_calls_per_task: int = 5

    def __post_init__(self) -> None:
        if not 1 <= self.max_active_tasks <= 100:
            raise ValueError("max_active_tasks MUST be in [1, 100]")
        if not 0 <= self.max_daily_cost_microusd <= 100_000_000:
            raise ValueError("max_daily_cost_microusd MUST be in [0, 100000000]")
        if not 1 <= self.max_wall_seconds_per_task <= 3_600:
            raise ValueError("max_wall_seconds_per_task MUST be in [1, 3600]")
        if not 1 <= self.max_tool_calls_per_task <= 100:
            raise ValueError("max_tool_calls_per_task MUST be in [1, 100]")


@dataclass(frozen=True, slots=True)
class BackgroundTaskQuotaUsage:
    active_tasks: int
    daily_cost_microusd: int

    def __post_init__(self) -> None:
        if min(self.active_tasks, self.daily_cost_microusd) < 0:
            raise ValueError("background task quota usage MUST be non-negative")


def enforce_background_task_quota(
    *,
    policy: BackgroundTaskQuotaPolicy,
    budget: BackgroundTaskBudget,
    usage: BackgroundTaskQuotaUsage,
) -> None:
    if budget.max_wall_seconds > policy.max_wall_seconds_per_task:
        raise BackgroundTaskQuotaExceededError("read investigation wall-clock quota exceeded")
    if budget.max_tool_calls > policy.max_tool_calls_per_task:
        raise BackgroundTaskQuotaExceededError("read investigation tool-call quota exceeded")
    if usage.active_tasks >= policy.max_active_tasks:
        raise BackgroundTaskQuotaExceededError("read investigation concurrency quota exceeded")
    if usage.daily_cost_microusd + budget.max_cost_microusd > policy.max_daily_cost_microusd:
        raise BackgroundTaskQuotaExceededError("read investigation daily cost quota exceeded")


def background_task_quota_usage(
    attempts: tuple[BackgroundTaskAttempt, ...],
    *,
    now: datetime,
) -> BackgroundTaskQuotaUsage:
    if now.tzinfo is None:
        raise ValueError("quota time MUST be timezone-aware")
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    active_tasks = 0
    daily_cost = 0
    for attempt in attempts:
        if attempt.task.owner_principal_id == "":  # pragma: no cover - model guard
            continue
        if attempt.status in ACTIVE_BACKGROUND_STATUSES:
            active_tasks += 1
        if not day_start <= attempt.task.created_at.astimezone(UTC) < day_end:
            continue
        daily_cost += (
            attempt.task.budget.max_cost_microusd
            if attempt.status in ACTIVE_BACKGROUND_STATUSES
            else attempt.usage.cost_microusd
        )
    return BackgroundTaskQuotaUsage(
        active_tasks=active_tasks,
        daily_cost_microusd=daily_cost,
    )


__all__ = [
    "ACTIVE_BACKGROUND_STATUSES",
    "BackgroundTaskQuotaExceededError",
    "BackgroundTaskQuotaPolicy",
    "BackgroundTaskQuotaUsage",
    "background_task_quota_usage",
    "enforce_background_task_quota",
]
