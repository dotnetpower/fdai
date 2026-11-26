"""Contract checks for the bounded Operator document-reference resolver."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "service-migrations/branches/operator-service/versions/"
    "20260914_operator_conversation_document_refs.py"
)


def test_document_ref_migration_keeps_raw_table_closed_and_function_bounded() -> None:
    module = runpy.run_path(str(MIGRATION))
    source = MIGRATION.read_text(encoding="utf-8")

    assert module["migration_owner"] == "operator-service"
    assert module["owned_tables"] == ()
    assert "REVOKE ALL PRIVILEGES ON TABLE document_version" in source
    assert "SECURITY DEFINER" in source
    assert "jsonb_array_length(p_refs) BETWEEN 1 AND 8" in source
    assert "version.state IN ('ready', 'ready_with_warnings')" in source
    assert "version.payload ->> 'index_state' = 'active'" in source
    assert "version.payload ->> 'retention_state' = 'live'" in source
    assert "version.payload ->> 'uploader_id' = p_principal_id" in source
    assert "reader_group.value = ANY(p_principal_groups)" in source
    assert "derived_expires_at" in source
    assert "GRANT EXECUTE ON FUNCTION fdai_resolve_conversation_document_refs" in source


def test_document_ref_migration_has_explicit_revoke_only_rollback() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "REVOKE EXECUTE ON FUNCTION fdai_resolve_conversation_document_refs" in source
    assert "DROP FUNCTION fdai_resolve_conversation_document_refs" in source
    assert "GRANT SELECT" not in source
