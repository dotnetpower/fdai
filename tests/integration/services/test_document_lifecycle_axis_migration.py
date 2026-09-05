"""Document lifecycle axis migration ownership tests."""

from __future__ import annotations

import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT / "service-migrations/branches/document-ingestion-api/versions/"
    "20260905_document_lifecycle_axes.py"
)


def test_deletion_axis_progress_is_narrow_and_worker_owned() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_MIGRATION))

    assert migration["owned_tables"] == ()
    assert "OLD.state = 'deleting'" in source
    assert "NEW.state = 'deleting'" in source
    assert "NEW.payload->>'index_state' = 'tombstoned'" in source
    assert "NEW.payload->>'retention_state' IN ('tombstoned', 'purge_pending')" in source
    assert "- 'updated_at' - 'active' - 'available'" in source
    assert "TG_TABLE_NAME <> 'document_version'" in source
