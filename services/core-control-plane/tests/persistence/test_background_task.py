from __future__ import annotations

import asyncio
import json
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
    PostgresBackgroundTaskProjectionFeed,
    PostgresBackgroundTaskProjectionFeedConfig,
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
)
from fdai_service_contracts.background_task_projection import (
    BackgroundTaskProjectionBudget,
    BackgroundTaskProjectionEnvelope,
    BackgroundTaskProjectionUsage,
    build_background_task_progress,
    build_background_task_snapshot,
)
from psycopg.rows import dict_row

_ROOT = Path(__file__).resolve().parents[4]
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


def _projection_outbox(dsn: str) -> PostgresBackgroundTaskProjectionFeed:
    return PostgresBackgroundTaskProjectionFeed(
        config=PostgresBackgroundTaskProjectionFeedConfig(dsn=dsn),
    )


async def _insert_projection_outbox_row(
    connection: psycopg.AsyncConnection[dict[str, object]],
    record: BackgroundTaskProjectionEnvelope,
) -> None:
    await connection.execute(
        """
        INSERT INTO background_task_projection_outbox (
            projection_id,
            task_id,
            attempt_id,
            record_kind,
            projection_sequence,
            progress_sequence,
            progress_order,
            progress_watermark,
            retention_until,
            payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            record.projection_id,
            record.task_id,
            record.attempt_id,
            record.record_kind,
            record.projection_sequence,
            record.progress_sequence,
            record.progress_order,
            record.progress_watermark,
            record.retention_until,
            json.dumps(record.model_dump(mode="json"), separators=(",", ":")),
        ),
    )


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
async def test_postgres_creation_audit_fences_claim_until_marked(
    database_url: str,
) -> None:
    task = _task(f"background-audit-fence-{uuid.uuid4().hex}")
    store = PostgresBackgroundTaskStore(
        config=PostgresBackgroundTaskStoreConfig(dsn=database_url),
        clock=lambda: _NOW,
    )
    created, was_created = await store.create(task, requires_creation_audit=True)

    assert await store.creation_audited(task.task_id) is False
    assert was_created is True
    assert created.revision == 1
    assert (
        await store.claim_next(
            coordinator="coordinator:audit-fence",
            lease_token="lease:audit-fence:blocked",
            now=_NOW,
            lease_seconds=30,
        )
        is None
    )

    audited = await store.mark_creation_audited(task.task_id, now=_NOW + timedelta(seconds=1))
    repeat = await store.mark_creation_audited(task.task_id, now=_NOW + timedelta(seconds=2))
    assert audited.revision == 2
    assert audited.updated_at == _NOW + timedelta(seconds=1)
    assert repeat == audited
    claimed = await store.claim_next(
        coordinator="coordinator:audit-fence",
        lease_token="lease:audit-fence:allowed",
        now=_NOW + timedelta(seconds=3),
        lease_seconds=30,
    )

    assert claimed is not None
    assert claimed.task.task_id == task.task_id
    assert claimed.revision == audited.revision + 1


@pytest.mark.integration
async def test_postgres_active_quota_crosses_utc_day_boundary(
    database_url: str,
) -> None:
    owner = f"{_OWNER_PREFIX}midnight-{uuid.uuid4().hex}"
    before_midnight = datetime(2026, 7, 20, 23, 59, 50, tzinfo=UTC)
    after_midnight = before_midnight + timedelta(seconds=20)
    first_task = replace(
        _task(f"background-midnight-a-{uuid.uuid4().hex}", owner=owner),
        created_at=before_midnight,
        retention_until=before_midnight + timedelta(days=1),
    )
    first = PostgresBackgroundTaskStore(
        config=PostgresBackgroundTaskStoreConfig(dsn=database_url),
        clock=lambda: before_midnight,
    )
    await first.create(first_task, quota=BackgroundTaskQuotaPolicy(max_active_tasks=1))
    second_task = replace(
        _task(f"background-midnight-b-{uuid.uuid4().hex}", owner=owner),
        created_at=after_midnight,
        retention_until=after_midnight + timedelta(days=1),
    )
    second = PostgresBackgroundTaskStore(
        config=PostgresBackgroundTaskStoreConfig(dsn=database_url),
        clock=lambda: after_midnight,
    )

    with pytest.raises(BackgroundTaskQuotaExceededError, match="concurrency"):
        await second.create(
            second_task,
            quota=BackgroundTaskQuotaPolicy(max_active_tasks=1),
        )


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
async def test_progress_append_order_and_terminal_watermark_are_persisted(
    database_url: str,
) -> None:
    task = _task(f"background-progress-watermark-{uuid.uuid4().hex}")
    store = _store(database_url)
    await store.create(task)
    claimed = await store.claim_next(
        coordinator="coordinator:progress-watermark",
        lease_token="lease:progress-watermark",
        now=_NOW,
        lease_seconds=30,
    )
    assert claimed is not None
    running = await store.start(
        claimed.attempt_id,
        expected_revision=claimed.revision,
        lease_token="lease:progress-watermark",
        now=_NOW + timedelta(seconds=1),
    )
    first = BackgroundTaskProgress(
        attempt_id=running.attempt_id,
        sequence=0,
        kind="investigation.started",
        message="Started bounded evidence collection.",
        at=_NOW + timedelta(seconds=2),
        usage=BackgroundTaskUsage(),
    )
    second = BackgroundTaskProgress(
        attempt_id=running.attempt_id,
        sequence=1,
        kind="investigation.progress",
        message="Captured the terminal dependency evidence.",
        at=_NOW + timedelta(seconds=3),
        usage=BackgroundTaskUsage(tool_calls=1),
    )

    await store.append_progress(first)
    await store.append_progress(second)
    result = _result(
        started_at=running.updated_at,
        finished_at=_NOW + timedelta(seconds=4),
    )
    await store.complete(
        running.attempt_id,
        expected_revision=running.revision,
        lease_token="lease:progress-watermark",
        status=BackgroundTaskStatus.SUCCEEDED,
        result=result,
        now=result.finished_at,
    )

    async with await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        progress_cursor = await connection.execute(
            "SELECT sequence, append_order FROM background_task_progress "
            "WHERE attempt_id = %s ORDER BY sequence ASC",
            (running.attempt_id,),
        )
        progress_rows = list(await progress_cursor.fetchall())
        completion_cursor = await connection.execute(
            "SELECT progress_watermark FROM background_task_completion WHERE attempt_id = %s",
            (running.attempt_id,),
        )
        completion_row = await completion_cursor.fetchone()
        outbox_cursor = await connection.execute(
            "SELECT record_kind, projection_sequence, progress_sequence, progress_order, "
            "progress_watermark, payload "
            "FROM background_task_projection_outbox WHERE attempt_id = %s "
            "ORDER BY outbox_sequence ASC",
            (running.attempt_id,),
        )
        outbox_rows = list(await outbox_cursor.fetchall())

    assert [row["sequence"] for row in progress_rows] == [0, 1]
    assert [row["append_order"] for row in progress_rows] == sorted(
        row["append_order"] for row in progress_rows
    )
    assert completion_row is not None
    assert completion_row["progress_watermark"] == progress_rows[-1]["append_order"]
    assert [row["record_kind"] for row in outbox_rows] == [
        "snapshot",
        "snapshot",
        "snapshot",
        "progress",
        "progress",
        "snapshot",
    ]
    assert [
        row["projection_sequence"] for row in outbox_rows if row["record_kind"] == "snapshot"
    ] == [100, 200, 300, 401]
    assert [
        row["progress_sequence"] for row in outbox_rows if row["record_kind"] == "progress"
    ] == [0, 1]
    assert [row["progress_order"] for row in outbox_rows if row["record_kind"] == "progress"] == [
        progress_rows[0]["append_order"],
        progress_rows[1]["append_order"],
    ]
    terminal_payload = BackgroundTaskProjectionEnvelope.model_validate(outbox_rows[-1]["payload"])
    assert terminal_payload.record_kind == "snapshot"
    assert terminal_payload.progress_watermark == progress_rows[-1]["append_order"]


@pytest.mark.integration
async def test_projection_outbox_replays_unacked_rows_and_skips_expired_data(
    database_url: str,
) -> None:
    active_task = _task(f"background-projection-replay-active-{uuid.uuid4().hex}")
    expired_task = replace(
        _task(f"background-projection-replay-expired-{uuid.uuid4().hex}"),
        created_at=_NOW - timedelta(days=2),
        retention_until=_NOW - timedelta(days=1),
    )
    active_attempt, _ = await _store(database_url).create(active_task)
    await _store(database_url).create(expired_task)
    outbox = _projection_outbox(database_url)

    claimed = await outbox.claim_batch(
        worker_id="projection-worker",
        lease_token="projection-lease-1",
        now=_NOW,
        lease_seconds=1,
        limit=10,
    )
    assert [item.task_id for item in claimed] == [active_task.task_id]
    assert claimed[0].projection_id.startswith("background-task-snapshot-")
    assert claimed[0].attempt_id == active_attempt.attempt_id

    assert (
        await outbox.claim_batch(
            worker_id="projection-worker",
            lease_token="projection-lease-2",
            now=_NOW,
            lease_seconds=1,
            limit=10,
        )
        == ()
    )

    replayed = await outbox.claim_batch(
        worker_id="projection-worker",
        lease_token="projection-lease-3",
        now=_NOW + timedelta(seconds=2),
        lease_seconds=1,
        limit=10,
    )
    assert [item.projection_id for item in replayed] == [claimed[0].projection_id]


@pytest.mark.integration
async def test_projection_outbox_blocks_terminal_snapshot_until_progress_is_published(
    database_url: str,
) -> None:
    task = _task(f"background-projection-order-{uuid.uuid4().hex}")
    attempt, _ = await _store(database_url).create(task)
    progress = build_background_task_progress(
        task_id=task.task_id,
        owner_principal_id=task.owner_principal_id,
        attempt_id=attempt.attempt_id,
        progress_sequence=0,
        progress_order=7,
        progress_kind="investigation.progress",
        progress_message="Collected the final bounded evidence.",
        progress_at=_NOW + timedelta(seconds=1),
        retention_until=task.retention_until,
        usage=BackgroundTaskProjectionUsage(tokens=1),
    )
    terminal = build_background_task_snapshot(
        task_id=task.task_id,
        owner_principal_id=task.owner_principal_id,
        attempt_id=attempt.attempt_id,
        task_kind="read_only_investigation",
        status="succeeded",
        revision=4,
        created_at=task.created_at,
        updated_at=_NOW + timedelta(seconds=2),
        retention_until=task.retention_until,
        recorded_at=_NOW + timedelta(seconds=2),
        budget=BackgroundTaskProjectionBudget(
            max_wall_seconds=task.budget.max_wall_seconds,
            max_tokens=task.budget.max_tokens,
            max_cost_microusd=task.budget.max_cost_microusd,
            max_tool_calls=task.budget.max_tool_calls,
            max_progress_events=task.budget.max_progress_events,
        ),
        usage=BackgroundTaskProjectionUsage(tokens=1),
        request_summary=task.prompt,
        request_truncated=False,
        result_summary="Investigation completed.",
        result_truncated=False,
        evidence_refs=(),
        evidence_truncated=False,
        terminal_reason="completed",
        started_at=_NOW,
        finished_at=_NOW + timedelta(seconds=2),
        completion_state="pending",
        completion_attempt_count=0,
        progress_watermark=7,
    )

    async with (
        await psycopg.AsyncConnection.connect(
            database_url,
            row_factory=dict_row,
        ) as connection,
        connection.transaction(),
    ):
        await connection.execute(
            "DELETE FROM background_task_projection_outbox WHERE attempt_id = %s",
            (attempt.attempt_id,),
        )
        await _insert_projection_outbox_row(connection, terminal)
        await _insert_projection_outbox_row(connection, progress)

    outbox = _projection_outbox(database_url)
    first_claim = await outbox.claim_batch(
        worker_id="projection-worker",
        lease_token="projection-order-1",
        now=_NOW + timedelta(seconds=3),
        lease_seconds=30,
        limit=10,
    )
    assert [item.projection_id for item in first_claim] == [progress.projection_id]
    assert first_claim[0].outbox_sequence > 0
    assert await outbox.acknowledge(
        progress.projection_id,
        lease_token="projection-order-1",
        published_at=_NOW + timedelta(seconds=3),
    )

    second_claim = await outbox.claim_batch(
        worker_id="projection-worker",
        lease_token="projection-order-2",
        now=_NOW + timedelta(seconds=4),
        lease_seconds=30,
        limit=10,
    )
    assert [item.projection_id for item in second_claim] == [terminal.projection_id]


@pytest.mark.integration
async def test_projection_outbox_never_skips_late_commit_with_smaller_sequence(
    database_url: str,
) -> None:
    first_task = _task(f"background-projection-reorder-a-{uuid.uuid4().hex}")
    second_task = _task(f"background-projection-reorder-b-{uuid.uuid4().hex}")
    first_attempt, _ = await _store(database_url).create(first_task)
    second_attempt, _ = await _store(database_url).create(second_task)
    first_record = build_background_task_progress(
        task_id=first_task.task_id,
        owner_principal_id=first_task.owner_principal_id,
        attempt_id=first_attempt.attempt_id,
        progress_sequence=0,
        progress_order=10,
        progress_kind="investigation.progress",
        progress_message="First transaction inserted earlier but committed later.",
        progress_at=_NOW + timedelta(seconds=1),
        retention_until=first_task.retention_until,
        usage=BackgroundTaskProjectionUsage(tokens=1),
    )
    second_record = build_background_task_progress(
        task_id=second_task.task_id,
        owner_principal_id=second_task.owner_principal_id,
        attempt_id=second_attempt.attempt_id,
        progress_sequence=0,
        progress_order=11,
        progress_kind="investigation.progress",
        progress_message="Second transaction committed before the smaller queue key.",
        progress_at=_NOW + timedelta(seconds=2),
        retention_until=second_task.retention_until,
        usage=BackgroundTaskProjectionUsage(tokens=2),
    )

    async with await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    ) as cleanup:
        await cleanup.execute(
            "DELETE FROM background_task_projection_outbox WHERE attempt_id = ANY(%s)",
            ([first_attempt.attempt_id, second_attempt.attempt_id],),
        )

    first_connection = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    second_connection = await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        await first_connection.execute("BEGIN")
        await second_connection.execute("BEGIN")
        await _insert_projection_outbox_row(first_connection, first_record)
        await _insert_projection_outbox_row(second_connection, second_record)
        await second_connection.commit()

        outbox = _projection_outbox(database_url)
        first_claim = await outbox.claim_batch(
            worker_id="projection-worker",
            lease_token="projection-reorder-1",
            now=_NOW + timedelta(seconds=3),
            lease_seconds=30,
            limit=10,
        )
        assert [item.projection_id for item in first_claim] == [second_record.projection_id]
        assert await outbox.acknowledge(
            second_record.projection_id,
            lease_token="projection-reorder-1",
            published_at=_NOW + timedelta(seconds=3),
        )

        await first_connection.commit()

        second_claim = await outbox.claim_batch(
            worker_id="projection-worker",
            lease_token="projection-reorder-2",
            now=_NOW + timedelta(seconds=4),
            lease_seconds=30,
            limit=10,
        )
        assert [item.projection_id for item in second_claim] == [first_record.projection_id]
    finally:
        await second_connection.close()
        await first_connection.close()


@pytest.mark.integration
async def test_postgres_rejects_progress_after_terminal_completion(
    database_url: str,
) -> None:
    task = _task(f"background-post-terminal-progress-{uuid.uuid4().hex}")
    store = _store(database_url)
    await store.create(task)
    claimed = await store.claim_next(
        coordinator="coordinator:post-terminal-progress",
        lease_token="lease:post-terminal-progress",
        now=_NOW,
        lease_seconds=30,
    )
    assert claimed is not None
    running = await store.start(
        claimed.attempt_id,
        expected_revision=claimed.revision,
        lease_token="lease:post-terminal-progress",
        now=_NOW + timedelta(seconds=1),
    )
    first = BackgroundTaskProgress(
        attempt_id=running.attempt_id,
        sequence=0,
        kind="investigation.started",
        message="Started bounded evidence collection.",
        at=_NOW + timedelta(seconds=2),
        usage=BackgroundTaskUsage(),
    )
    assert await store.append_progress(first) == first
    result = _result(
        started_at=running.updated_at,
        finished_at=_NOW + timedelta(seconds=3),
    )
    await store.complete(
        running.attempt_id,
        expected_revision=running.revision,
        lease_token="lease:post-terminal-progress",
        status=BackgroundTaskStatus.SUCCEEDED,
        result=result,
        now=result.finished_at,
    )

    with pytest.raises(BackgroundTaskConflictError, match="terminal state"):
        await store.append_progress(
            BackgroundTaskProgress(
                attempt_id=running.attempt_id,
                sequence=1,
                kind="investigation.completed",
                message="Tried to append after completion.",
                at=_NOW + timedelta(seconds=4),
                usage=BackgroundTaskUsage(tokens=1),
            )
        )

    async with await psycopg.AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    ) as connection:
        progress_cursor = await connection.execute(
            "SELECT COUNT(*) AS event_count, MAX(append_order) AS max_append_order "
            "FROM background_task_progress WHERE attempt_id = %s",
            (running.attempt_id,),
        )
        progress_row = await progress_cursor.fetchone()
        completion_cursor = await connection.execute(
            "SELECT progress_watermark FROM background_task_completion WHERE attempt_id = %s",
            (running.attempt_id,),
        )
        completion_row = await completion_cursor.fetchone()

    assert progress_row is not None
    assert progress_row["event_count"] == 1
    assert completion_row is not None
    assert completion_row["progress_watermark"] == progress_row["max_append_order"]


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
