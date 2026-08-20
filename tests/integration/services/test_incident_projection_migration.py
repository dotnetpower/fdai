from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260819_core_incident_projection.py"
)


def test_incident_projection_backfill_initializes_each_correlation_once() -> None:
    migration_source = MIGRATION.read_text(encoding="utf-8")
    backfill = migration_source.split("DO $backfill$", maxsplit=1)[1].split(
        "$backfill$;", maxsplit=1
    )[0]

    assert "SELECT COALESCE(MAX(seq), 0)" in backfill
    assert "SELECT DISTINCT COALESCE(" in backfill
    assert "PERFORM fdai_refresh_operator_incident_projection(candidate, snapshot_seq)" in backfill
    assert "FOR audit_row IN SELECT * FROM audit_log" not in backfill
    assert "PERFORM fdai_project_operator_incident_audit_row(audit_row)" not in backfill
