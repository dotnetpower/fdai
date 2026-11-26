"""Pin the Core conversation assurance writer privilege boundary."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260917_core_conversation_assurance_writer.py"
)
_TABLES = {
    "conversation_assurance_assessment",
    "conversation_assurance_dispute",
}


def test_core_conversation_assurance_writer_grant_is_append_only() -> None:
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        migration = runpy.run_path(str(_MIGRATION))
        migration["upgrade"]()

    upgrade_sql = " ".join(statements)
    assert migration["revision"] == "core_conversation_assurance_writer_20260917"
    assert migration["down_revision"] == "core_cost_governance_live_20260917"
    assert migration["migration_owner"] == "core-control-plane"
    assert migration["owned_tables"] == ()
    assert "GRANT SELECT, INSERT ON TABLE" in upgrade_sql
    assert "TO fdai_core" in upgrade_sql
    grant_sql = upgrade_sql.split("GRANT SELECT, INSERT ON TABLE", 1)[1]
    assert "UPDATE" not in grant_sql
    assert "DELETE" not in grant_sql


def test_core_conversation_assurance_writer_grant_is_reversible() -> None:
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        migration = runpy.run_path(str(_MIGRATION))
        migration["downgrade"]()

    downgrade_sql = " ".join(statements)
    assert "REVOKE ALL PRIVILEGES ON TABLE" in downgrade_sql
    assert "FROM fdai_core" in downgrade_sql
    assert "DROP TABLE" not in downgrade_sql


def test_assurance_tables_have_one_core_writer_and_operator_migrator() -> None:
    manifest = json.loads((_ROOT / "service-migrations/ownership.json").read_text())
    assert _TABLES <= set(manifest["table_migrations"]["operator-service"])
    assert _TABLES <= set(manifest["whole_table_writers"]["core-control-plane"])
    assert _TABLES.isdisjoint(manifest["whole_table_writers"]["operator-service"])
