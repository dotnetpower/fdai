from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskBudget,
    BackgroundTaskCompletionState,
    BackgroundTaskConflictError,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskProgress,
    BackgroundTaskQuotaExceededError,
    BackgroundTaskQuotaPolicy,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskUsage,
)
from fdai.delivery.persistence import (
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
)

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)
_OWNER_PREFIX = "test-background-task-"


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
async def database_url() -> str:
    dsn = _dsn()
    _upgrade()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "DELETE FROM background_task_attempt WHERE owner_principal_id LIKE %s",
            (f"{_OWNER_PREFIX}%",),
        )
    return dsn


def _store(dsn: str) -> BackgroundTaskStore:
    store = PostgresBackgroundTaskStore(
        config=PostgresBackgroundTaskStoreConfig(dsn=dsn),
        clock=lambda: _NOW,
    )
    protocol_store: BackgroundTaskStore = store
    return protocol_store


def _task(
    task_id: str,
    *,
    owner: str | None = None,
    max_progress_events: int = 3,
) -> BackgroundTask:
    task_owner = owner or f"{_OWNER_PREFIX}owner"
    return BackgroundTask(
        task_id=task_id,
        owner_principal_id=task_owner,
        origin=BackgroundTaskOrigin(
            conversation_id=f"conversation:{task_id}",
            channel_kind="web",
            channel_id="channel:example",
            thread_id="thread:example",
        ),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence without mutation.",
        context_digest=f"sha256:{task_id}",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(max_progress_events=max_progress_events),
        correlation_id=f"correlation:{task_id}",
        idempotency_key=f"idempotency:{task_id}",
        created_at=_NOW,
        retention_until=_NOW + timedelta(days=30),
    )


def _result(*, started_at: datetime, finished_at: datetime) -> BackgroundTaskResult:
    return BackgroundTaskResult(
        summary="Bounded investigation completed.",
        evidence_refs=("evidence:one",),
        terminal_reason="completed",
        usage=BackgroundTaskUsage(tokens=21, cost_microusd=7, tool_calls=2),
        started_at=started_at,
        finished_at=finished_at,
    )


async def _complete_succeeded(
    store: BackgroundTaskStore,
    task: BackgroundTask,
    *,
    lease_token: str,
    now: datetime,
) -> None:
    await store.create(task)
    claimed = await store.claim_next(
        coordinator=f"coordinator:{task.task_id}",
        lease_token=lease_token,
        now=now,
        lease_seconds=30,
    )
    assert claimed is not None
    running = await store.start(
        claimed.attempt_id,
        expected_revision=claimed.revision,
        lease_token=lease_token,
        now=now + timedelta(seconds=1),
    )
    await store.complete(
        running.attempt_id,
        expected_revision=running.revision,
        lease_token=lease_token,
        status=BackgroundTaskStatus.SUCCEEDED,
        result=_result(
            started_at=running.updated_at,
            finished_at=now + timedelta(seconds=2),
        ),
        now=now + timedelta(seconds=2),
    )


@pytest.mark.integration
async def test_two_postgres_stores_claim_one_attempt_exactly_once(
    database_url: str,
) -> None:
    task = _task(f"background-claim-{uuid.uuid4().hex}")
    first = _store(database_url)
    second = _store(database_url)
    stored, created = await first.create(task)
    assert created and stored.status is BackgroundTaskStatus.QUEUED

    claims = await asyncio.gather(
        first.claim_next(
            coordinator="coordinator:first",
            lease_token="lease:first",
            now=_NOW,
            lease_seconds=30,
        ),
        second.claim_next(
            coordinator="coordinator:second",
            lease_token="lease:second",
            now=_NOW,
            lease_seconds=30,
        ),
    )

    assert sum(claim is not None for claim in claims) == 1
    claimed = next(claim for claim in claims if claim is not None)
    assert claimed.status is BackgroundTaskStatus.CLAIMED
    assert claimed.revision == 2


@pytest.mark.integration
async def test_two_postgres_stores_enforce_owner_quota_atomically(
    database_url: str,
) -> None:
    owner = f"{_OWNER_PREFIX}quota-{uuid.uuid4().hex}"
    first_task = _task(f"background-quota-a-{uuid.uuid4().hex}", owner=owner)
    second_task = _task(f"background-quota-b-{uuid.uuid4().hex}", owner=owner)
    first = _store(database_url)
    second = _store(database_url)
    policy = BackgroundTaskQuotaPolicy(max_active_tasks=1)

    outcomes = await asyncio.gather(
        first.create(first_task, quota=policy),
        second.create(second_task, quota=policy),
        return_exceptions=True,
    )

    assert sum(isinstance(item, tuple) for item in outcomes) == 1
    assert sum(isinstance(item, BackgroundTaskQuotaExceededError) for item in outcomes) == 1
    stored_task = first_task if isinstance(outcomes[0], tuple) else second_task
    store = first if stored_task is first_task else second
    retried, created = await store.create(stored_task, quota=policy)
    assert created is False
    assert retried.task == stored_task


@pytest.mark.integration
async def test_postgres_store_rejects_client_selected_quota_day(
    database_url: str,
) -> None:
    task = replace(
        _task(f"background-backdated-{uuid.uuid4().hex}"),
        created_at=_NOW - timedelta(days=1),
        retention_until=_NOW + timedelta(days=1),
    )

    with pytest.raises(ValueError, match="within 300 seconds of server time"):
        await _store(database_url).create(task, quota=BackgroundTaskQuotaPolicy())


@pytest.mark.integration
async def test_start_renew_completion_and_terminal_immutability(
    database_url: str,
) -> None:
    task = _task(f"background-lifecycle-{uuid.uuid4().hex}")
    store = _store(database_url)
    await store.create(task)
    claimed = await store.claim_next(
        coordinator="coordinator:lifecycle",
        lease_token="lease:lifecycle",
        now=_NOW,
        lease_seconds=30,
    )
    assert claimed is not None
    running = await store.start(
        claimed.attempt_id,
        expected_revision=claimed.revision,
        lease_token="lease:lifecycle",
        now=_NOW + timedelta(seconds=1),
    )
    renewed = await store.renew(
        running.attempt_id,
        expected_revision=running.revision,
        lease_token="lease:lifecycle",
        now=_NOW + timedelta(seconds=2),
        lease_seconds=30,
        usage=BackgroundTaskUsage(tokens=8, tool_calls=1),
    )
    result = _result(
        started_at=running.updated_at,
        finished_at=_NOW + timedelta(seconds=3),
    )
    completed = await store.complete(
        renewed.attempt_id,
        expected_revision=renewed.revision,
        lease_token="lease:lifecycle",
        status=BackgroundTaskStatus.SUCCEEDED,
        result=result,
        now=result.finished_at,
    )

    assert completed.result == result
    assert completed.usage == result.usage
    assert completed.lease is None
    with pytest.raises(BackgroundTaskConflictError):
        await store.complete(
            completed.attempt_id,
            expected_revision=completed.revision,
            lease_token="lease:lifecycle",
            status=BackgroundTaskStatus.FAILED,
            result=result,
            now=result.finished_at,
        )


@pytest.mark.integration
async def test_expired_lease_and_owner_scope_fail_closed(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}owner-scope"
    task = _task(f"background-owner-{uuid.uuid4().hex}", owner=owner)
    store = _store(database_url)
    await store.create(task)
    claimed = await store.claim_next(
        coordinator="coordinator:expiry",
        lease_token="lease:expiry",
        now=_NOW,
        lease_seconds=1,
    )
    assert claimed is not None

    assert await store.get(task.task_id, owner="another-owner") is None
    assert await store.list(owner="another-owner") == ()
    with pytest.raises(BackgroundTaskConflictError):
        await store.start(
            claimed.attempt_id,
            expected_revision=claimed.revision,
            lease_token="lease:expiry",
            now=_NOW + timedelta(seconds=1),
        )
    with pytest.raises(PermissionError):
        await store.cancel(
            task.task_id,
            actor="another-owner",
            is_admin=False,
            now=_NOW + timedelta(seconds=2),
        )

    cancelled = await store.cancel(
        task.task_id,
        actor="admin-principal",
        is_admin=True,
        now=_NOW + timedelta(seconds=2),
    )
    assert cancelled.status is BackgroundTaskStatus.CANCELLED
    assert cancelled.result is not None
    assert cancelled.result.terminal_reason == "cancelled_by_operator"

    owner_task = _task(f"background-owner-cancel-{uuid.uuid4().hex}", owner=owner)
    await store.create(owner_task)
    owner_cancelled = await store.cancel(
        owner_task.task_id,
        actor=owner,
        is_admin=False,
        now=_NOW + timedelta(seconds=3),
    )
    assert owner_cancelled.status is BackgroundTaskStatus.CANCELLED


@pytest.mark.integration
async def test_progress_sequence_budget_and_owner_scope(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}progress-owner"
    task = _task(
        f"background-progress-{uuid.uuid4().hex}",
        owner=owner,
        max_progress_events=2,
    )
    store = _store(database_url)
    attempt, _ = await store.create(task)
    first = BackgroundTaskProgress(
        attempt_id=attempt.attempt_id,
        sequence=0,
        kind="investigation.started",
        message="Started bounded evidence collection.",
        at=_NOW,
        usage=BackgroundTaskUsage(),
    )
    second = BackgroundTaskProgress(
        attempt_id=attempt.attempt_id,
        sequence=1,
        kind="investigation.progress",
        message="Collected one bounded evidence reference.",
        at=_NOW + timedelta(seconds=1),
        usage=BackgroundTaskUsage(tool_calls=1),
    )

    assert await store.append_progress(first) == first
    with pytest.raises(BackgroundTaskConflictError):
        await store.append_progress(replace(second, sequence=2))
    assert await store.append_progress(second) == second
    assert await store.progress(task.task_id, owner=owner) == (first, second)
    with pytest.raises(LookupError):
        await store.progress(task.task_id, owner="another-owner")
    with pytest.raises(BackgroundTaskConflictError):
        await store.append_progress(
            BackgroundTaskProgress(
                attempt_id=attempt.attempt_id,
                sequence=2,
                kind="investigation.progress",
                message="This event exceeds the task budget.",
                at=_NOW + timedelta(seconds=2),
                usage=second.usage,
            )
        )


@pytest.mark.integration
async def test_idempotent_create_and_restart_round_trip(database_url: str) -> None:
    owner = f"{_OWNER_PREFIX}restart-owner"
    task = _task(f"background-restart-{uuid.uuid4().hex}", owner=owner)
    store = _store(database_url)
    initial, created = await store.create(task)
    duplicate, duplicate_created = await store.create(task)
    conflicting = replace(
        task,
        task_id=f"background-conflict-{uuid.uuid4().hex}",
        context_digest="sha256:conflicting-task",
        correlation_id="correlation:conflicting-task",
    )
    with pytest.raises(BackgroundTaskConflictError):
        await store.create(conflicting)

    restarted = _store(database_url)
    loaded = await restarted.get(task.task_id, owner=owner)
    listed = await restarted.list(owner=owner)

    assert created is True
    assert duplicate_created is False
    assert duplicate == initial
    assert loaded == initial
    assert task.task_id in {attempt.task.task_id for attempt in listed}


@pytest.mark.integration
async def test_expired_lease_reconciles_to_unknown_without_requeue(
    database_url: str,
) -> None:
    task = _task(f"background-expired-{uuid.uuid4().hex}")
    store = _store(database_url)
    await store.create(task)
    claimed = await store.claim_next(
        coordinator="coordinator:expired",
        lease_token="lease:expired",
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
            coordinator="coordinator:next",
            lease_token="lease:next",
            now=_NOW + timedelta(seconds=2),
            lease_seconds=30,
        )
        is None
    )


@pytest.mark.integration
async def test_completion_claim_is_atomic_across_stores(database_url: str) -> None:
    task = _task(f"background-completion-claim-{uuid.uuid4().hex}")
    first = _store(database_url)
    second = _store(database_url)
    await _complete_succeeded(first, task, lease_token="lease:complete", now=_NOW)

    claims = await asyncio.gather(
        first.claim_completion(
            coordinator="completion:first",
            lease_token="lease:delivery:first",
            now=_NOW + timedelta(seconds=3),
            lease_seconds=30,
        ),
        second.claim_completion(
            coordinator="completion:second",
            lease_token="lease:delivery:second",
            now=_NOW + timedelta(seconds=3),
            lease_seconds=30,
        ),
    )

    assert sum(claim is not None for claim in claims) == 1
    claimed = next(claim for claim in claims if claim is not None)
    assert claimed is not None
    completion, attempt = claimed
    assert completion.state is BackgroundTaskCompletionState.SENDING
    assert completion.attempt_count == 1
    assert attempt.attempt_id == completion.attempt_id


@pytest.mark.integration
async def test_completion_retry_then_delivery(database_url: str) -> None:
    task = _task(f"background-completion-retry-{uuid.uuid4().hex}")
    store = _store(database_url)
    await _complete_succeeded(store, task, lease_token="lease:retry", now=_NOW)

    claimed = await store.claim_completion(
        coordinator="completion:retry",
        lease_token="lease:retry:1",
        now=_NOW + timedelta(seconds=3),
        lease_seconds=30,
    )
    assert claimed is not None
    failed = await store.finish_completion(
        claimed[0].attempt_id,
        lease_token="lease:retry:1",
        delivered=False,
        now=_NOW + timedelta(seconds=4),
        retry_at=_NOW + timedelta(seconds=5),
        error_code="transport_error",
    )
    assert failed.state is BackgroundTaskCompletionState.FAILED
    assert failed.last_error_code == "transport_error"
    assert failed.terminal_at is None

    retried = await store.claim_completion(
        coordinator="completion:retry",
        lease_token="lease:retry:2",
        now=_NOW + timedelta(seconds=5),
        lease_seconds=30,
    )
    assert retried is not None
    delivered = await store.finish_completion(
        retried[0].attempt_id,
        lease_token="lease:retry:2",
        delivered=True,
        now=_NOW + timedelta(seconds=6),
    )
    assert delivered.state is BackgroundTaskCompletionState.DELIVERED
    assert delivered.attempt_count == 2
    assert delivered.terminal_at == _NOW + timedelta(seconds=6)


@pytest.mark.integration
async def test_completion_expired_delivery_lease_recovers_to_failed(
    database_url: str,
) -> None:
    task = _task(f"background-completion-expired-{uuid.uuid4().hex}")
    store = _store(database_url)
    await _complete_succeeded(store, task, lease_token="lease:expired-complete", now=_NOW)

    claimed = await store.claim_completion(
        coordinator="completion:expired",
        lease_token="lease:expired:1",
        now=_NOW + timedelta(seconds=3),
        lease_seconds=1,
    )
    assert claimed is not None

    recovered = await store.reconcile_completion_expired(now=_NOW + timedelta(seconds=4))
    assert len(recovered) == 1
    completion = recovered[0]
    assert completion.state is BackgroundTaskCompletionState.FAILED
    assert completion.last_error_code == "process_lost"
    assert completion.terminal_at is None

    claimed_again = await store.claim_completion(
        coordinator="completion:expired",
        lease_token="lease:expired:2",
        now=_NOW + timedelta(seconds=4),
        lease_seconds=30,
    )
    assert claimed_again is not None
    assert claimed_again[0].attempt_count == 2


@pytest.mark.integration
async def test_completion_retention_blocks_then_allows_purge(database_url: str) -> None:
    store = _store(database_url)
    active_task = _task(f"background-completion-retain-active-{uuid.uuid4().hex}")
    expired_task = replace(
        _task(f"background-completion-retain-expired-{uuid.uuid4().hex}"),
        created_at=_NOW - timedelta(days=2),
        retention_until=_NOW - timedelta(days=1),
    )
    await _complete_succeeded(store, active_task, lease_token="lease:retain-active", now=_NOW)
    await _complete_succeeded(
        store,
        expired_task,
        lease_token="lease:retain-expired",
        now=_NOW - timedelta(days=2),
    )

    active_claim = await store.claim_completion(
        coordinator="completion:retain",
        lease_token="lease:retain:active",
        now=_NOW + timedelta(seconds=3),
        lease_seconds=30,
    )
    assert active_claim is not None
    await store.finish_completion(
        active_claim[0].attempt_id,
        lease_token="lease:retain:active",
        delivered=True,
        now=_NOW + timedelta(seconds=4),
    )

    expired_claim = await store.claim_completion(
        coordinator="completion:retain",
        lease_token="lease:retain:expired",
        now=_NOW + timedelta(seconds=5),
        lease_seconds=30,
    )
    assert expired_claim is not None
    await store.finish_completion(
        expired_claim[0].attempt_id,
        lease_token="lease:retain:expired",
        delivered=True,
        now=_NOW + timedelta(seconds=6),
    )

    blocked = await store.purge_retained(now=_NOW, limit=10)
    assert active_task.task_id not in blocked
    assert expired_task.task_id in blocked

    active_after = await store.get(active_task.task_id)
    expired_after = await store.get(expired_task.task_id)
    assert active_after is not None
    assert expired_after is None
