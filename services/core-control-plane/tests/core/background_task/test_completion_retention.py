"""Focused retention checks for undeliverable background completions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
    InMemoryBackgroundTaskStore,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)


async def test_pending_completion_is_abandoned_and_purgeable_at_retention() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    task = BackgroundTask(
        task_id="background-retention",
        owner_principal_id="principal-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "principal-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=NOW,
        retention_until=NOW + timedelta(seconds=1),
    )
    attempt, _created = await store.create(task)
    claimed = await store.claim_next(
        coordinator="coordinator-one",
        lease_token="lease-one",
        now=NOW,
        lease_seconds=30,
    )
    assert claimed is not None
    running = await store.start(
        claimed.attempt_id,
        expected_revision=claimed.revision,
        lease_token="lease-one",
        now=NOW,
    )
    result = BackgroundTaskResult(
        summary="Complete",
        evidence_refs=(),
        terminal_reason="matched",
        usage=BackgroundTaskUsage(),
        started_at=NOW,
        finished_at=NOW,
    )
    await store.complete(
        running.attempt_id,
        expected_revision=running.revision,
        lease_token="lease-one",
        status=BackgroundTaskStatus.SUCCEEDED,
        result=result,
        now=NOW,
    )

    reconciled = await store.reconcile_completion_expired(now=NOW + timedelta(seconds=2))
    purged = await store.purge_retained(now=NOW + timedelta(seconds=2))

    assert reconciled[0].state.value == "abandoned"
    assert reconciled[0].last_error_code == "retention_expired"
    assert purged == (attempt.task.task_id,)
