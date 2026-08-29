from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_MIGRATION = (
    REPO_ROOT / "alembic/versions/20260829_0088_background_task_completion_updated_at.py"
)
CORE_GRANT_MIGRATION = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260829_core_background_task_progress_order.py"
)
OWNERSHIP_PATH = REPO_ROOT / "service-migrations/ownership.json"


def test_legacy_background_task_transport_migration_creates_outbox_and_progress_guard() -> None:
    source = ROOT_MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE background_task_projection_outbox" in source
    assert "record_kind IN ('snapshot', 'progress')" in source
    assert "CREATE INDEX ix_background_task_projection_outbox_pending" in source
    assert "CREATE INDEX ix_background_task_projection_outbox_attempt_progress" in source
    assert "DROP TABLE IF EXISTS background_task_projection_outbox" in source
    assert "ADD COLUMN progress_watermark BIGINT" in source
    assert "ADD COLUMN updated_at TIMESTAMPTZ" in source


def test_core_transport_grant_exposes_only_outbox_and_required_sequences() -> None:
    source = CORE_GRANT_MIGRATION.read_text(encoding="utf-8")

    assert "GRANT SELECT, INSERT, UPDATE ON TABLE background_task_projection_outbox" in source
    assert "background_task_progress_append_order_seq" in source
    assert "background_task_projection_outbox_outbox_sequence_seq" in source
    assert "GRANT DELETE ON TABLE background_task_projection_outbox" not in source
    assert "ALTER DEFAULT PRIVILEGES" not in source


def test_background_task_projection_outbox_is_tracked_by_migration_ownership_manifest() -> None:
    ownership = json.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))

    assert ownership["legacy_inventory"]["table_count"] == 104
    assert "background_task_projection_outbox" in ownership["table_migrations"]["operator-service"]
    assert (
        "background_task_projection_outbox" in ownership["whole_table_writers"]["operator-service"]
    )
