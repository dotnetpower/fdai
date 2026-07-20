from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.trajectory import InMemoryTrajectoryDatasetStore, TrajectoryRetentionService
from fdai.shared.providers.trajectory import TrajectoryDatasetRecord, TrajectoryDatasetState

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


class ArtifactDeleter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    async def delete(self, storage_ref: str) -> None:
        if self.fail:
            raise RuntimeError("artifact delete failed")
        self.deleted.append(storage_ref)


def _record(dataset_id: str, *, legal_hold: bool = False) -> TrajectoryDatasetRecord:
    return TrajectoryDatasetRecord(
        dataset_id=dataset_id,
        purpose="quality-review",
        access_scope="scope-example",
        principal_scope_digest="a" * 64,
        state=TrajectoryDatasetState.COMPLETED,
        schema_version="1.0",
        storage_ref=f"dataset:{dataset_id}",
        record_count=3,
        dataset_checksum="b" * 64,
        manifest_checksum="c" * 64,
        created_at=NOW - timedelta(days=40),
        retention_until=NOW - timedelta(days=2),
        deletion_due_at=NOW - timedelta(days=1),
        legal_hold=legal_hold,
        legal_hold_ref="hold-review" if legal_hold else None,
    )


async def test_retention_deletes_due_dataset_but_preserves_legal_hold() -> None:
    store = InMemoryTrajectoryDatasetStore()
    artifacts = ArtifactDeleter()
    await store.put(_record("delete-me"))
    await store.put(_record("held", legal_hold=True))

    deleted = await TrajectoryRetentionService(store=store, artifacts=artifacts).delete_due(
        now=NOW, limit=100
    )

    assert deleted == ("delete-me",)
    assert artifacts.deleted == ["dataset:delete-me"]
    removed = await store.get("delete-me", access_scope="scope-example")
    held = await store.get("held", access_scope="scope-example")
    assert removed is not None
    assert removed.state is TrajectoryDatasetState.DELETED
    assert removed.storage_ref is None
    assert removed.deleted_at == NOW
    assert held is not None
    assert held.state is TrajectoryDatasetState.COMPLETED
    assert held.storage_ref == "dataset:held"


async def test_retention_keeps_metadata_retryable_when_artifact_delete_fails() -> None:
    store = InMemoryTrajectoryDatasetStore()
    await store.put(_record("retry-me"))

    with pytest.raises(RuntimeError, match="artifact delete failed"):
        await TrajectoryRetentionService(
            store=store,
            artifacts=ArtifactDeleter(fail=True),
        ).delete_due(now=NOW)

    record = await store.get("retry-me", access_scope="scope-example")
    assert record is not None
    assert record.state is TrajectoryDatasetState.COMPLETED
    assert record.storage_ref == "dataset:retry-me"
    assert record.deleted_at is None


async def test_dataset_store_denies_cross_scope_reads() -> None:
    store = InMemoryTrajectoryDatasetStore()
    await store.put(_record("dataset-1"))

    assert await store.get("dataset-1", access_scope="other-scope") is None
    assert await store.list(access_scope="other-scope", purpose="quality-review", limit=10) == ()
