"""Pin the aggregate-only retention read and non-destructive rollback contract."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT / "service-migrations/branches/operator-service/versions/"
    "20260917_operator_forecast_retention.py"
)


def test_forecast_retention_view_exposes_only_aggregate_read() -> None:
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        migration = runpy.run_path(str(_MIGRATION))
        migration["upgrade"]()
    sql = " ".join(statements)
    assert migration["migration_owner"] == "operator-service"
    assert migration["owned_tables"] == ()
    assert "WITH (security_barrier = true)" in sql
    assert "AS pending" in sql and "AS overdue" in sql
    assert "GRANT SELECT ON TABLE operator_forecast_retention TO fdai_operator" in sql
    assert "GRANT SELECT ON TABLE case_history" not in sql
    assert "GRANT CREATE" not in sql
    assert "SELECT *" not in sql
    assert "FROM PUBLIC" in sql


def test_forecast_retention_rollback_drops_only_view() -> None:
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        runpy.run_path(str(_MIGRATION))["downgrade"]()
    sql = " ".join(statements)
    assert "DROP VIEW operator_forecast_retention" in sql
    assert "case_history" not in sql
    assert "DELETE" not in sql and "DROP TABLE" not in sql


def test_forecast_retention_declares_core_source_dependency() -> None:
    manifest = json.loads((_ROOT / "service-migrations/ownership.json").read_text())
    dependencies = [
        item
        for item in manifest["migration_dependencies"]
        if item["consumer_revision"] == "operator_forecast_retention_20260917"
    ]
    assert len(dependencies) == 1
    assert dependencies[0]["provider_service"] == "core-control-plane"
    assert dependencies[0]["schema_prerequisites"] == ["case_history"]
