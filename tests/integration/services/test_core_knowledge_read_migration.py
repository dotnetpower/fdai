"""Contract checks for the bounded Core knowledge-search migration."""

from __future__ import annotations

import runpy
from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations/branches/core-control-plane/versions/20260917_core_knowledge_read.py"
)


class _CaptureOp:
    statements: list[str]

    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_core_knowledge_search_excludes_governed_rows_and_raw_table_grants() -> None:
    migration = runpy.run_path(str(_MIGRATION))
    capture = _CaptureOp()
    migration["upgrade"].__globals__["op"] = capture

    migration["upgrade"]()

    sql = "\n".join(capture.statements)
    assert migration["revision"] == "core_knowledge_read_20260917"
    assert migration["down_revision"] == "core_conversation_assurance_writer_20260917"
    assert "SECURITY DEFINER" in sql
    assert "p_limit BETWEEN 1 AND 20" in sql
    assert "governed_document" in sql
    assert "REVOKE ALL ON FUNCTION" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "GRANT SELECT" not in sql


def test_core_knowledge_search_downgrade_revokes_and_drops_function() -> None:
    migration = runpy.run_path(str(_MIGRATION))
    capture = _CaptureOp()
    migration["downgrade"].__globals__["op"] = capture

    migration["downgrade"]()

    sql = "\n".join(capture.statements)
    assert "REVOKE ALL ON FUNCTION" in sql
    assert "DROP FUNCTION" in sql
