from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.delivery.persistence.postgres_trajectory import (
    PostgresTrajectoryStoreConfig,
    _row_to_record,
    _values,
)
from fdai.shared.providers.trajectory import TrajectoryDatasetRecord, TrajectoryDatasetState

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _record() -> TrajectoryDatasetRecord:
    return TrajectoryDatasetRecord(
        dataset_id="dataset-example",
        purpose="quality-review",
        access_scope="scope-example",
        principal_scope_digest="a" * 64,
        state=TrajectoryDatasetState.COMPLETED,
        schema_version="1.0",
        storage_ref="dataset:example",
        record_count=6,
        dataset_checksum="b" * 64,
        manifest_checksum="c" * 64,
        created_at=NOW,
        retention_until=NOW + timedelta(days=30),
        deletion_due_at=NOW + timedelta(days=31),
    )


def test_trajectory_dataset_row_codec_round_trips() -> None:
    columns = (
        "dataset_id purpose access_scope principal_scope_digest state schema_version "
        "storage_ref record_count dataset_checksum manifest_checksum created_at "
        "retention_until deletion_due_at legal_hold legal_hold_ref deleted_at"
    ).split()
    record = _record()

    assert _row_to_record(dict(zip(columns, _values(record), strict=True))) == record


def test_trajectory_postgres_config_fails_fast() -> None:
    with pytest.raises(ValueError, match="MUST NOT be empty"):
        PostgresTrajectoryStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts MUST be positive"):
        PostgresTrajectoryStoreConfig(dsn="postgresql://example", statement_timeout_ms=0)


def test_migration_is_linear_and_retention_excludes_legal_hold() -> None:
    migration = (ROOT / "alembic/versions/20260720_0048_trajectory_dataset.py").read_text(
        encoding="utf-8"
    )
    store = (ROOT / "src/fdai/delivery/persistence/postgres_trajectory.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "20260720_0048"' in migration
    assert 'down_revision: str | None = "20260720_0047"' in migration
    assert "legal_hold = FALSE" in migration
    assert "legal_hold = FALSE" in store
    assert "trajectory dataset is under legal hold" in store
