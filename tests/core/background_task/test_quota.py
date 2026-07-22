from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskQuotaExceededError,
    BackgroundTaskQuotaPolicy,
    InMemoryBackgroundTaskStore,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _task(index: int, *, owner: str = "principal:one") -> BackgroundTask:
    return BackgroundTask(
        task_id=f"task:{index}",
        owner_principal_id=owner,
        origin=BackgroundTaskOrigin("conversation:one", "web", "channel:one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(
            max_wall_seconds=60,
            max_cost_microusd=400_000,
            max_tool_calls=5,
        ),
        correlation_id=f"correlation:{index}",
        idempotency_key=f"idempotency:{index}",
        created_at=NOW,
        retention_until=NOW + timedelta(days=1),
    )


async def test_store_enforces_concurrency_and_daily_reserved_cost_atomically() -> None:
    store = InMemoryBackgroundTaskStore()
    policy = BackgroundTaskQuotaPolicy(
        max_active_tasks=2,
        max_daily_cost_microusd=1_000_000,
    )
    await store.create(_task(1), quota=policy)
    await store.create(_task(2), quota=policy)
    with pytest.raises(BackgroundTaskQuotaExceededError, match="concurrency"):
        await store.create(_task(3), quota=policy)

    other, created = await store.create(_task(4, owner="principal:two"), quota=policy)
    assert created is True
    assert other.task.owner_principal_id == "principal:two"


async def test_idempotent_retry_returns_existing_task_even_when_quota_is_full() -> None:
    store = InMemoryBackgroundTaskStore()
    task = _task(1)
    policy = BackgroundTaskQuotaPolicy(max_active_tasks=1)
    first, created = await store.create(task, quota=policy)
    retried, retry_created = await store.create(task, quota=policy)
    assert created is True
    assert retry_created is False
    assert retried == first


async def test_store_rejects_per_task_wall_tool_and_daily_cost_budgets() -> None:
    store = InMemoryBackgroundTaskStore()
    policy = BackgroundTaskQuotaPolicy(
        max_active_tasks=3,
        max_daily_cost_microusd=500_000,
        max_wall_seconds_per_task=60,
        max_tool_calls_per_task=5,
    )
    with pytest.raises(BackgroundTaskQuotaExceededError, match="wall-clock"):
        await store.create(
            replace(
                _task(1),
                budget=replace(_task(1).budget, max_wall_seconds=61),
            ),
            quota=policy,
        )
    with pytest.raises(BackgroundTaskQuotaExceededError, match="tool-call"):
        await store.create(
            replace(
                _task(2),
                budget=replace(_task(2).budget, max_tool_calls=6),
            ),
            quota=policy,
        )
    await store.create(_task(3), quota=policy)
    with pytest.raises(BackgroundTaskQuotaExceededError, match="daily cost"):
        await store.create(_task(4), quota=policy)
