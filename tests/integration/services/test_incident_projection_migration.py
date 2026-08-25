from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260819_core_incident_projection.py"
)
CANONICAL_MIGRATION = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260825_core_canonical_incident_projection.py"
)


def test_incident_projection_backfill_initializes_each_correlation_once() -> None:
    migration_source = MIGRATION.read_text(encoding="utf-8")
    backfill = migration_source.rsplit("INSERT INTO operator_incident_projection (", maxsplit=1)[
        1
    ].split("CREATE TRIGGER", maxsplit=1)[0]

    assert "SELECT COALESCE(MAX(seq), 0)" in backfill
    assert "PARTITION BY normalized_correlation_id" in backfill
    assert "GROUP BY normalized_correlation_id" in backfill
    assert "HAVING BOOL_OR(NOT platform_activity)" in backfill
    assert "FILTER (WHERE recent_rank <= 100)" in backfill
    assert "PERFORM fdai_refresh_operator_incident_projection" not in backfill
    assert "FOR candidate IN" not in backfill
    assert "FOR audit_row IN SELECT * FROM audit_log" not in backfill
    assert "PERFORM fdai_project_operator_incident_audit_row(audit_row)" not in backfill


def test_canonical_incident_projection_uses_unbounded_lifecycle_evidence() -> None:
    base_source = MIGRATION.read_text(encoding="utf-8")
    migration_source = CANONICAL_MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN has_canonical_incident BOOLEAN NOT NULL DEFAULT FALSE" in migration_source
    assert "ADD COLUMN canonical_incident_id TEXT" in migration_source
    assert "ADD COLUMN canonical_incident_number TEXT" in migration_source
    assert "ADD COLUMN canonical_ticket_id TEXT" in migration_source
    assert "ADD COLUMN canonical_opened_at TEXT" in migration_source
    assert "operator_incident_projection_canonical_identity_ck" in migration_source
    assert "opened.entry->>'kind' = 'incident.open'" in migration_source
    assert "ticket.entry->>'kind' = 'incident.ticket'" in migration_source
    assert "projection.valid_from_seq" in migration_source
    assert "audit_row.seq" in migration_source
    assert "JSONB_ARRAY_ELEMENTS" not in migration_source
    assert "audit_log_zz_operator_incident_canonical" in migration_source
    assert "audit_log_operator_incident_projection" in base_source
    assert "audit_log_zz_operator_incident_canonical" > "audit_log_operator_incident_projection"
    assert "DROP FUNCTION fdai_canonical_incident_identity(TEXT, BIGINT)" in migration_source
    assert "DROP COLUMN has_canonical_incident" in migration_source
