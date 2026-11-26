"""Document lifecycle axis migration ownership tests."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT / "service-migrations/branches/document-ingestion-api/versions/"
    "20260905_document_lifecycle_axes.py"
)
_CONVERGENCE_MIGRATION = (
    _ROOT / "service-migrations/branches/document-ingestion-api/versions/"
    "20260905_document_lifecycle_convergence.py"
)


def test_deletion_axis_progress_is_narrow_and_worker_owned() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_MIGRATION))

    assert migration["owned_tables"] == ()
    assert migration["down_revision"] == "native_sharepoint_resync_state_20260905"
    assert "OLD.state = 'deleting'" in source
    assert "NEW.state = 'deleting'" in source
    assert "NEW.payload->>'index_state' = 'tombstoned'" in source
    assert "NEW.payload->>'retention_state' IN ('tombstoned', 'purge_pending')" in source
    assert "OLD.state = 'deleted'" in source
    assert "NEW.payload->>'index_state' = 'purged'" in source
    assert "NEW.payload->>'retention_state' = 'purged'" in source
    assert "- 'updated_at' - 'active' - 'available'" in source
    assert "TG_TABLE_NAME <> 'document_version'" in source
    assert "NEW.payload->>'active' = 'false'" in source
    assert "NEW.payload->>'available' = 'false'" in source
    assert "rights_managed_access_denied" in source
    assert "api_allowed IS NOT TRUE" in source
    assert "worker_allowed IS NOT TRUE" in source


def test_terminal_convergence_guard_is_table_specific_and_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = runpy.run_path(str(_CONVERGENCE_MIGRATION))
    statements: list[str] = []
    monkeypatch.setattr(migration["op"], "execute", statements.append)

    migration["upgrade"]()

    assert migration["owned_tables"] == ()
    assert migration["down_revision"] == "ingestion_lifecycle_axes_20260905"
    assert len(statements) == 1
    sql = statements[0]
    assert "TG_TABLE_NAME = 'document_version'" in sql
    assert "TG_TABLE_NAME = 'document_upload_session'" in sql
    assert "OLD.payload - 'revision' - 'index_state' - 'retention_state'" in sql
    assert "NEW.payload - 'revision' - 'index_state' - 'retention_state'" in sql
    assert "OLD.state = 'deleted'" in sql
    assert "NEW.state = 'deleted'" in sql
    assert "NEW.payload->>'index_state' = 'purged'" in sql
    assert "NEW.payload->>'retention_state' = 'purged'" in sql
    assert "worker_allowed IS NOT TRUE" in sql
