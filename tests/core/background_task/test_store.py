from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskBudget,
    BackgroundTaskConflictError,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
    InMemoryBackgroundTaskStore,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _task(task_id: str = "background-one") -> BackgroundTask:
    return BackgroundTask(
        task_id=task_id,
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id=f"correlation:{task_id}",
        idempotency_key=f"idempotency:{task_id}",
        created_at=_NOW,
        retention_until=_NOW + timedelta(days=30),
    )


async def test_only_one_concurrent_coordinator_claims_queued_attempt() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task())

    claims = await asyncio.gather(
        store.claim_next(
            coordinator="coordinator-one",
            lease_token="lease-one",
            now=_NOW,
            lease_seconds=30,
        ),
        store.claim_next(
            coordinator="coordinator-two",
            lease_token="lease-two",
            now=_NOW,
            lease_seconds=30,
        ),
    )

    assert sum(item is not None for item in claims) == 1
    claimed = next(item for item in claims if item is not None)
    assert claimed.status is BackgroundTaskStatus.CLAIMED


async def test_lease_revision_and_terminal_state_are_immutable() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task())
    claimed = await store.claim_next(
        coordinator="coordinator-one",
        lease_token="lease-one",
        now=_NOW,
        lease_seconds=30,
    )
    assert claimed is not None
    running = await store.start(
        claimed.attempt_id,
        expected_revision=claimed.revision,
        lease_token="lease-one",
        now=_NOW + timedelta(seconds=1),
    )
    result = BackgroundTaskResult(
        summary="Completed.",
        evidence_refs=("evidence:one",),
        terminal_reason="completed",
        usage=BackgroundTaskUsage(tokens=10),
        started_at=_NOW + timedelta(seconds=1),
        finished_at=_NOW + timedelta(seconds=2),
    )
    completed = await store.complete(
        running.attempt_id,
        expected_revision=running.revision,
        lease_token="lease-one",
        status=BackgroundTaskStatus.SUCCEEDED,
        result=result,
        now=result.finished_at,
    )

    assert completed.result == result and completed.lease is None
    with pytest.raises(BackgroundTaskConflictError):
        await store.complete(
            running.attempt_id,
            expected_revision=running.revision,
            lease_token="lease-one",
            status=BackgroundTaskStatus.FAILED,
            result=result,
            now=result.finished_at,
        )


async def test_owner_scope_and_cancellation_are_enforced() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task())

    assert await store.get("background-one", owner="operator-two") is None
    assert await store.list(owner="operator-two") == ()
    with pytest.raises(PermissionError):
        await store.cancel(
            "background-one",
            actor="operator-two",
            is_admin=False,
            now=_NOW,
        )
    cancelled = await store.cancel(
        "background-one",
        actor="operator-one",
        is_admin=False,
        now=_NOW,
    )
    assert cancelled.status is BackgroundTaskStatus.CANCELLED


async def test_expired_lease_reconciles_to_unknown_without_requeue() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task())
    claimed = await store.claim_next(
        coordinator="coordinator-one",
        lease_token="lease-one",
        now=_NOW,
        lease_seconds=1,
    )
    assert claimed is not None

    reconciled = await store.reconcile_expired(now=_NOW + timedelta(seconds=1))

    assert len(reconciled) == 1
    assert reconciled[0].status is BackgroundTaskStatus.UNKNOWN
    assert reconciled[0].result is not None
    assert reconciled[0].result.terminal_reason == "process_lost"
    assert (
        await store.claim_next(
            coordinator="coordinator-two",
            lease_token="lease-two",
            now=_NOW + timedelta(seconds=2),
            lease_seconds=30,
        )
        is None
    )
