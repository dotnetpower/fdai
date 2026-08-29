"""Focused tests for Operator background-task projection ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.background_task_projection_runtime import (
    BackgroundTaskProjectionBridge,
    BackgroundTaskProjectionConsumer,
)
from fdai_operator_service.postgres_background_task_projection import (
    BackgroundTaskProjectionConflictError,
    PostgresBackgroundTaskProjectionRepository,
    StoredBackgroundTaskProjectionRecord,
)
from fdai_service_contracts.background_task_projection import (
    BackgroundTaskProjectionBudget,
    BackgroundTaskProjectionEnvelope,
    BackgroundTaskProjectionUsage,
    build_background_task_progress,
    build_background_task_snapshot,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _snapshot(**updates: object) -> BackgroundTaskProjectionEnvelope:
    values: dict[str, object] = {
        "task_id": "background-task-one",
        "owner_principal_id": "principal-one",
        "attempt_id": "background-task-one:1",
        "task_kind": "read_only_investigation",
        "status": "succeeded",
        "revision": 5,
        "created_at": NOW,
        "updated_at": NOW,
        "retention_until": NOW + timedelta(days=30),
        "recorded_at": NOW + timedelta(seconds=2),
        "usage": BackgroundTaskProjectionUsage(tokens=3, cost_microusd=5, tool_calls=1),
        "budget": BackgroundTaskProjectionBudget(
            max_wall_seconds=300,
            max_tokens=4096,
            max_cost_microusd=500000,
            max_tool_calls=5,
            max_progress_events=32,
        ),
        "request_summary": "Inspect the deployment drift.",
        "request_truncated": False,
        "accountable_agent": "Heimdall",
        "result_summary": "The deployment completed successfully.",
        "result_truncated": False,
        "evidence_refs": ("evidence-one",),
        "evidence_truncated": False,
        "terminal_reason": "completed",
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=1),
        "completion_state": "delivered",
        "completion_attempt_count": 1,
        "progress_watermark": 2,
    }
    values.update(updates)
    return build_background_task_snapshot(**values)  # type: ignore[arg-type]


def _progress(**updates: object) -> BackgroundTaskProjectionEnvelope:
    values: dict[str, object] = {
        "task_id": "background-task-one",
        "owner_principal_id": "principal-one",
        "attempt_id": "background-task-one:1",
        "progress_sequence": 0,
        "progress_order": 1,
        "progress_kind": "investigation.progress",
        "progress_message": "Collected the authoritative state.",
        "progress_at": NOW,
        "retention_until": NOW + timedelta(days=30),
        "usage": BackgroundTaskProjectionUsage(tokens=1),
    }
    values.update(updates)
    return build_background_task_progress(**values)  # type: ignore[arg-type]


async def test_repository_accepts_exact_duplicate_and_ignores_older_snapshot() -> None:
    snapshot = _snapshot()
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return [
            {
                "task_id": snapshot.task_id,
                "principal_id": snapshot.owner_principal_id,
                "projection_id": snapshot.projection_id,
                "projection_digest": snapshot.projection_digest,
                "projection_sequence": snapshot.projection_sequence,
                "applied": False,
            }
        ]

    repository = PostgresBackgroundTaskProjectionRepository(fetch_all=fetch_all)

    stored = await repository.project_background_task_projection(snapshot)
    older = await repository.project_background_task_projection(
        _snapshot(
            revision=4,
            completion_state="pending",
            completion_attempt_count=0,
            result_summary="Older result",
            terminal_reason="pending_delivery",
            finished_at=NOW,
        )
    )

    assert stored.duplicate is True
    assert older.duplicate is True
    assert "INSERT INTO operator_background_task_projection" in calls[0][0]
    assert "progress_watermark" in calls[0][0]
    assert calls[0][1]["principal_id"] == "principal-one"
    assert calls[0][1]["progress_watermark"] == 2


async def test_repository_rejects_cross_owner_snapshot_conflict() -> None:
    snapshot = _snapshot()

    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return [
            {
                "task_id": snapshot.task_id,
                "principal_id": "principal-two",
                "projection_id": snapshot.projection_id,
                "projection_digest": snapshot.projection_digest,
                "projection_sequence": snapshot.projection_sequence,
                "applied": False,
            }
        ]

    with pytest.raises(BackgroundTaskProjectionConflictError, match="owner conflicts"):
        await PostgresBackgroundTaskProjectionRepository(
            fetch_all=fetch_all
        ).project_background_task_projection(snapshot)


async def test_repository_rejects_progress_identity_conflict() -> None:
    progress = _progress()
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return [
            {
                "task_id": progress.task_id,
                "principal_id": progress.owner_principal_id,
                "progress_id": progress.projection_id,
                "progress_digest": "sha256:" + "0" * 64,
                "progress_order": progress.progress_order,
                "progress_sequence": progress.progress_sequence,
                "inserted": False,
            }
        ]

    with pytest.raises(BackgroundTaskProjectionConflictError, match="identity conflicts"):
        await PostgresBackgroundTaskProjectionRepository(
            fetch_all=fetch_all
        ).project_background_task_projection(progress)
    assert "progress_order" in calls[0][0]
    assert calls[0][1]["progress_order"] == 1


async def test_repository_ignores_expired_projection_without_recreating_operator_rows() -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return []

    repository = PostgresBackgroundTaskProjectionRepository(
        fetch_all=fetch_all,
        clock=lambda: NOW + timedelta(days=31),
    )

    expired_snapshot = await repository.project_background_task_projection(
        _snapshot(retention_until=NOW + timedelta(days=1))
    )
    expired_progress = await repository.project_background_task_projection(
        _progress(retention_until=NOW + timedelta(days=1))
    )

    assert expired_snapshot.duplicate is True
    assert expired_snapshot.record_kind == "snapshot"
    assert expired_progress.duplicate is True
    assert expired_progress.record_kind == "progress"
    assert calls == []


async def test_repository_purge_is_bounded() -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return [{"task_id": "background-task-one"}]

    deleted = await PostgresBackgroundTaskProjectionRepository(
        fetch_all=fetch_all
    ).purge_expired_background_task_projections(now=NOW, limit=17)

    assert deleted == 2
    assert "DELETE FROM operator_background_task_projection" in calls[0][0]
    assert "DELETE FROM operator_background_task_progress" in calls[1][0]
    assert calls[0][1] == {"now": NOW, "limit": 17}


class _Store:
    def __init__(self) -> None:
        self.records: list[BackgroundTaskProjectionEnvelope] = []
        self.retention_calls: list[tuple[datetime, int]] = []
        self.retention_started = asyncio.Event()

    async def project_background_task_projection(
        self,
        record: BackgroundTaskProjectionEnvelope,
    ) -> StoredBackgroundTaskProjectionRecord:
        self.records.append(record)
        return StoredBackgroundTaskProjectionRecord(
            task_id=record.task_id,
            principal_id=record.owner_principal_id,
            record_kind=record.record_kind,
            sequence=(record.projection_sequence or record.progress_sequence or 0),
            projection_id=record.projection_id,
            duplicate=False,
        )

    async def purge_expired_background_task_projections(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> int:
        self.retention_calls.append((now, limit))
        self.retention_started.set()
        return 0


async def test_consumer_validates_versioned_projection_before_store() -> None:
    store = _Store()
    payload = _snapshot().model_dump(mode="json")

    await BackgroundTaskProjectionConsumer(store).consume(payload)

    assert store.records[0].record_kind == "snapshot"


class _Source:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.started = asyncio.Event()
        self.closed = 0

    async def probe_readiness(self) -> bool:
        return True

    async def _stream(self) -> AsyncIterator[Mapping[str, object]]:
        self.started.set()
        try:
            yield self.payload
            await asyncio.Event().wait()
        finally:
            self.closed += 1

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[Mapping[str, object]]:
        assert topic == "core.background-task.projections"
        assert group_id == "operator-background-task-projection-v1"
        return self._stream()


class _Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        self.published.append((topic, key, payload))
        return object()


class _FailingSource:
    def __init__(self) -> None:
        self.attempts = 0

    async def probe_readiness(self) -> bool:
        self.attempts += 1
        return False

    async def _stream(self) -> AsyncIterator[Mapping[str, object]]:
        raise RuntimeError("projection source unavailable")
        if False:  # pragma: no cover - preserves the async-iterator contract
            yield {}

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[Mapping[str, object]]:
        del topic, group_id
        return self._stream()


async def test_bridge_quarantines_invalid_projection_and_tracks_retention_health() -> None:
    source = _Source({"projection_id": "unsafe\nprojection", "schema_version": "1.0.0"})
    publisher = _Publisher()
    store = _Store()
    bridge = BackgroundTaskProjectionBridge(
        store=store,
        source=source,
        publisher=publisher,
        retry_seconds=0.001,
        retention_interval_seconds=30,
        retention_batch_size=7,
        clock=lambda: NOW,
    )

    await bridge.start()
    await asyncio.wait_for(source.started.wait(), timeout=1)
    await asyncio.wait_for(store.retention_started.wait(), timeout=1)
    for _ in range(100):
        if publisher.published:
            break
        await asyncio.sleep(0.001)
    assert bridge.workers_ready() is True

    await bridge.aclose()

    assert source.closed == 1
    assert publisher.published[0][0] == "core.background-task.projections.dlq"
    assert publisher.published[0][1].startswith("invalid-background-task-")
    assert store.retention_calls == [(NOW, 7)]


async def test_bridge_readiness_fails_closed_when_projection_source_retries() -> None:
    source = _FailingSource()
    store = _Store()
    bridge = BackgroundTaskProjectionBridge(
        store=store,
        source=source,
        publisher=_Publisher(),
        retry_seconds=0.001,
        retention_interval_seconds=30,
        clock=lambda: NOW,
    )

    await bridge.start()
    await asyncio.wait_for(store.retention_started.wait(), timeout=1)
    for _ in range(100):
        if source.attempts:
            break
        await asyncio.sleep(0.001)

    assert source.attempts >= 1
    assert bridge.workers_ready() is False
    await bridge.aclose()
