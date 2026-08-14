"""Live PostgreSQL coverage for trajectory metadata retention."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fdai.core.trajectory import TrajectoryRetentionService
from fdai.delivery.persistence import (
    PostgresTrajectoryDatasetStore,
    PostgresTrajectoryDatasetStoreConfig,
)
from fdai.shared.providers.trajectory import TrajectoryDatasetRecord, TrajectoryDatasetState

_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
_DELETION_CLAIM_MIGRATION = _ROOT / "alembic/versions/20260814_0084_trajectory_deletion_claim.py"


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


def test_deletion_claim_migration_blocks_unsafe_downgrade() -> None:
    migration = runpy.run_path(str(_DELETION_CLAIM_MIGRATION))
    guard = migration["_ACTIVE_DELETION_GUARD_SQL"]

    assert isinstance(guard, str)
    assert "cannot downgrade while trajectory deletion claims are active" in guard


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


class _ArtifactDeleter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    async def delete(self, storage_ref: str) -> None:
        if self.fail:
            raise RuntimeError("artifact delete failed")
        self.deleted.append(storage_ref)


async def _cleanup(*dataset_ids: str) -> None:
    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        await connection.execute(
            "DELETE FROM trajectory_dataset WHERE dataset_id = ANY(%s)",
            (list(dataset_ids),),
        )
        await connection.commit()


@pytest.mark.integration
async def test_dataset_metadata_survives_restart_and_hides_other_scopes() -> None:
    _upgrade()
    suffix = uuid.uuid4().hex
    dataset_id = f"trajectory-{suffix}"
    other_id = f"trajectory-other-{suffix}"
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    record = _record(dataset_id)
    other = _record(other_id, scope="scope-other")
    try:
        assert await store.put(record) == record
        assert await store.put(record) == record
        await store.put(other)

        restarted = PostgresTrajectoryDatasetStore(
            config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn())
        )
        assert await restarted.get(dataset_id, access_scope="scope-example") == record
        assert await restarted.get(dataset_id, access_scope="scope-other") is None
        assert await restarted.list(
            access_scope="scope-example", purpose="quality-review", limit=10
        ) == (record,)
        with pytest.raises(ValueError, match="different metadata"):
            await restarted.put(replace(record, purpose="different-purpose"))
    finally:
        await _cleanup(dataset_id, other_id)


@pytest.mark.integration
async def test_legal_hold_is_monotonic_and_excludes_due_records() -> None:
    _upgrade()
    suffix = uuid.uuid4().hex
    due_id = f"trajectory-a-due-{suffix}"
    held_id = f"trajectory-z-held-{suffix}"
    missing_id = f"trajectory-missing-{suffix}"
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    try:
        due = await store.put(_record(due_id))
        held = await store.put(_record(held_id))
        assert await store.list(
            access_scope="scope-example", purpose="quality-review", limit=10
        ) == (held, due)

        assert await store.place_legal_hold(dataset_id=held_id, hold_ref="case:example")
        assert not await store.place_legal_hold(dataset_id=held_id, hold_ref="case:example")
        with pytest.raises(ValueError, match="different legal hold"):
            await store.place_legal_hold(dataset_id=held_id, hold_ref="case:conflict")
        assert await store.place_legal_hold(dataset_id=missing_id, hold_ref="case:none") is None

        assert await store.list_due(now=_NOW, limit=10) == (due,)
        with pytest.raises(PermissionError, match="legal hold"):
            await store.mark_deleted(held_id, deleted_at=_NOW)
        with pytest.raises(RuntimeError, match="state changed concurrently"):
            await store.mark_deleted(due_id, deleted_at=_NOW)
        with pytest.raises(ValueError, match="timezone"):
            await store.list_due(now=_NOW.replace(tzinfo=None), limit=10)
        with pytest.raises(ValueError, match="timezone"):
            await store.claim_deletion(due_id, now=_NOW.replace(tzinfo=None))
        with pytest.raises(ValueError, match="timezone"):
            await store.mark_deleted(due_id, deleted_at=_NOW.replace(tzinfo=None))
    finally:
        await _cleanup(due_id, held_id)


@pytest.mark.integration
async def test_legal_hold_is_rechecked_before_metadata_tombstone() -> None:
    _upgrade()
    dataset_id = f"trajectory-hold-{uuid.uuid4().hex}"
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    try:
        record = await store.put(_record(dataset_id))
        assert await store.list_due(now=_NOW, limit=10) == (record,)
        async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
            await connection.execute(
                "UPDATE trajectory_dataset SET legal_hold = TRUE, legal_hold_ref = %s "
                "WHERE dataset_id = %s",
                ("hold-review", dataset_id),
            )
            await connection.commit()

        assert await store.claim_deletion(dataset_id, now=_NOW) is None
        held = await store.get(dataset_id, access_scope="scope-example")
        assert held is not None
        assert held.state is TrajectoryDatasetState.COMPLETED
        assert held.storage_ref == f"dataset:{dataset_id}"
    finally:
        await _cleanup(dataset_id)


@pytest.mark.integration
async def test_deletion_claim_rejects_late_legal_hold() -> None:
    _upgrade()
    dataset_id = f"trajectory-claimed-{uuid.uuid4().hex}"
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    try:
        await store.put(_record(dataset_id))
        claimed = await store.claim_deletion(dataset_id, now=_NOW)
        assert claimed is not None and claimed.state is TrajectoryDatasetState.DELETING

        with pytest.raises(ValueError, match="cannot be placed under legal hold"):
            await store.place_legal_hold(dataset_id=dataset_id, hold_ref="hold-too-late")

        with pytest.raises(psycopg.errors.CheckViolation):
            async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
                await connection.execute(
                    "UPDATE trajectory_dataset SET legal_hold = TRUE, legal_hold_ref = %s "
                    "WHERE dataset_id = %s",
                    ("hold-too-late", dataset_id),
                )
    finally:
        await _cleanup(dataset_id)


@pytest.mark.integration
async def test_active_deletion_claim_blocks_live_downgrade_guard() -> None:
    _upgrade()
    dataset_id = f"trajectory-downgrade-{uuid.uuid4().hex}"
    store = PostgresTrajectoryDatasetStore(config=PostgresTrajectoryDatasetStoreConfig(dsn=_dsn()))
    try:
        await store.put(_record(dataset_id))
        claimed = await store.claim_deletion(dataset_id, now=_NOW)
        assert claimed is not None and claimed.state is TrajectoryDatasetState.DELETING
        guard = runpy.run_path(str(_DELETION_CLAIM_MIGRATION))["_ACTIVE_DELETION_GUARD_SQL"]
        assert isinstance(guard, str)

        connection = await psycopg.AsyncConnection.connect(_dsn())
        try:
            with pytest.raises(psycopg.Error) as captured:
                await connection.execute(guard)
            assert captured.value.sqlstate == "55000"
            await connection.rollback()
        finally:
            await connection.close()
    finally:
        await _cleanup(dataset_id)


@pytest.mark.integration
async def test_artifact_delete_failure_remains_retryable_after_restart() -> None:
    _upgrade()
    dataset_id = f"trajectory-retry-{uuid.uuid4().hex}"
    config = PostgresTrajectoryDatasetStoreConfig(dsn=_dsn())
    store = PostgresTrajectoryDatasetStore(config=config)
    try:
        await store.put(_record(dataset_id))
        with pytest.raises(RuntimeError, match="artifact delete failed"):
            await TrajectoryRetentionService(
                store=store,
                artifacts=_ArtifactDeleter(fail=True),
            ).delete_due(now=_NOW)

        restarted = PostgresTrajectoryDatasetStore(config=config)
        retryable = await restarted.get(dataset_id, access_scope="scope-example")
        assert retryable is not None
        assert retryable.state is TrajectoryDatasetState.DELETING
        assert retryable.storage_ref == f"dataset:{dataset_id}"

        artifacts = _ArtifactDeleter()
        assert await TrajectoryRetentionService(
            store=restarted,
            artifacts=artifacts,
        ).delete_due(now=_NOW) == (dataset_id,)
        assert artifacts.deleted == [f"dataset:{dataset_id}"]
        deleted = await restarted.get(dataset_id, access_scope="scope-example")
        assert deleted is not None
        assert deleted.state is TrajectoryDatasetState.DELETED
        assert deleted.storage_ref is None
        assert deleted.deleted_at == _NOW
        assert await restarted.mark_deleted(dataset_id, deleted_at=_NOW) == deleted
    finally:
        await _cleanup(dataset_id)
