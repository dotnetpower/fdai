"""Live PostgreSQL coverage for governed trajectory dataset custody."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fdai.core.trajectory import TrajectoryRetentionService
from fdai.delivery.persistence import (
    PostgresTrajectoryDatasetStore,
    PostgresTrajectoryDatasetStoreConfig,
)
from fdai.shared.providers.trajectory import TrajectoryDatasetRecord, TrajectoryDatasetState

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


class _ArtifactDeleter:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.deleted: list[str] = []

    async def delete(self, storage_ref: str) -> None:
        if self._fail:
            raise RuntimeError("artifact delete failed")
        self.deleted.append(storage_ref)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _record(dataset_id: str, *, scope: str = "scope-example") -> TrajectoryDatasetRecord:
    return TrajectoryDatasetRecord(
        dataset_id=dataset_id,
        purpose="quality-review",
        access_scope=scope,
        principal_scope_digest="a" * 64,
        state=TrajectoryDatasetState.COMPLETED,
        schema_version="1.0",
        storage_ref=f"dataset:{dataset_id}",
        record_count=3,
        dataset_checksum="b" * 64,
        manifest_checksum="c" * 64,
        created_at=_NOW - timedelta(days=40),
        retention_until=_NOW - timedelta(days=2),
        deletion_due_at=_NOW - timedelta(days=1),
    )


def test_postgres_trajectory_config_rejects_invalid_settings() -> None:
    with pytest.raises(ValueError, match="DSN"):
        PostgresTrajectoryDatasetStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresTrajectoryDatasetStoreConfig(dsn="postgresql://example", statement_timeout_ms=0)


@pytest.mark.integration
async def test_postgres_trajectory_restart_scope_idempotency_and_legal_hold() -> None:
    _upgrade()
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    suffix = uuid4().hex
    due = _record(f"due-{suffix}")
    held = _record(f"held-{suffix}")
    other_scope = _record(f"other-{suffix}", scope="other-scope")

    assert await store.put(due) == due
    assert await store.put(due) == due
    with pytest.raises(ValueError, match="reused with different metadata"):
        await store.put(replace(due, record_count=4))
    await store.put(held)
    await store.put(other_scope)

    restarted = PostgresTrajectoryDatasetStore(
        config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn())
    )
    assert await restarted.get(due.dataset_id, access_scope=due.access_scope) == due
    assert await restarted.get(due.dataset_id, access_scope="other-scope") is None
    assert await restarted.list(
        access_scope=due.access_scope,
        purpose=due.purpose,
        limit=100,
    ) == (held, due)

    assert await restarted.place_legal_hold(dataset_id=held.dataset_id, hold_ref="case:example")
    assert (
        await restarted.place_legal_hold(dataset_id=held.dataset_id, hold_ref="case:example")
        is False
    )
    with pytest.raises(ValueError, match="different legal hold"):
        await restarted.place_legal_hold(dataset_id=held.dataset_id, hold_ref="case:conflict")
    assert (
        await restarted.place_legal_hold(
            dataset_id=f"missing-{suffix}",
            hold_ref="case:none",
        )
        is None
    )

    due_records = await restarted.list_due(now=_NOW, limit=100)
    assert due.dataset_id in {record.dataset_id for record in due_records}
    assert held.dataset_id not in {record.dataset_id for record in due_records}
    with pytest.raises(PermissionError, match="legal hold"):
        await restarted.mark_deleted(held.dataset_id, deleted_at=_NOW)


@pytest.mark.integration
async def test_postgres_trajectory_retention_is_retryable_before_tombstone() -> None:
    _upgrade()
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    record = _record(f"retry-{uuid4().hex}")
    await store.put(record)

    with pytest.raises(RuntimeError, match="artifact delete failed"):
        await TrajectoryRetentionService(
            store=store,
            artifacts=_ArtifactDeleter(fail=True),
        ).delete_due(now=_NOW, limit=100)

    restarted = PostgresTrajectoryDatasetStore(
        config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn())
    )
    assert await restarted.get(record.dataset_id, access_scope=record.access_scope) == record

    artifacts = _ArtifactDeleter()
    deleted = await TrajectoryRetentionService(store=restarted, artifacts=artifacts).delete_due(
        now=_NOW,
        limit=100,
    )
    assert record.dataset_id in deleted
    assert record.storage_ref in artifacts.deleted
    tombstone = await restarted.get(record.dataset_id, access_scope=record.access_scope)
    assert tombstone is not None
    assert tombstone.state is TrajectoryDatasetState.DELETED
    assert tombstone.storage_ref is None
    assert tombstone.deleted_at == _NOW
    assert await restarted.mark_deleted(record.dataset_id, deleted_at=_NOW) == tombstone
