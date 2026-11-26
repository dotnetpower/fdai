from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[3]
_CORE_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260917_core_cost_governance_live_projection.py"
)
_OPERATOR_MIGRATION = (
    _ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260917_operator_cost_governance_live_read.py"
)


def _migration_sql(path: Path) -> tuple[dict[str, object], str]:
    module = runpy.run_path(str(path))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    return module, "\n".join(statements)


def test_core_migration_adds_content_free_runs_and_explicit_case_frames() -> None:
    module, sql = _migration_sql(_CORE_MIGRATION)

    assert module["migration_owner"] == "core-control-plane"
    assert set(module["owned_tables"]) == {
        "cost_observation_current",
        "cost_governance_analytics_run_receipt",
        "cost_governance_case_projection",
        "cost_governance_settlement",
    }
    assert "status IN ('complete', 'partial', 'failed', 'disabled')" in sql
    assert "CREATE TABLE cost_observation_current" in sql
    assert "PRIMARY KEY (package_id, scope_id, service_id, currency, event_day)" in sql
    assert "recorded_at DESC, observation_id DESC" in sql
    assert "scope_digest TEXT NOT NULL" in sql
    assert "target_refs JSONB NOT NULL" in sql
    assert "options JSONB NOT NULL" in sql
    assert "verdict TEXT NOT NULL CHECK (verdict = 'hold')" in sql
    assert "ADD COLUMN currency TEXT NULL" in sql
    assert "ADD COLUMN action_revision BIGINT NULL" in sql
    assert "(action_ref IS NULL) = (action_revision IS NULL)" in sql
    assert "GRANT SELECT, INSERT ON TABLE" in " ".join(sql.split())
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql


def test_operator_migration_grants_read_only_lineage_access() -> None:
    module, sql = _migration_sql(_OPERATOR_MIGRATION)

    assert module["migration_owner"] == "operator-service"
    assert module["owned_tables"] == ()
    assert module["migration_prerequisites"] == {
        "service": "core-control-plane",
        "revision": "core_cost_governance_live_20260917",
    }
    for table in (
        "cost_governance_analytics_run_receipt",
        "cost_observation_current",
        "cost_governance_case_projection",
        "cost_governance_episode",
        "cost_governance_evidence",
        "cost_governance_recovery",
        "cost_governance_retention",
        "cost_governance_settlement",
        "cost_governance_effect_settlement",
    ):
        assert table in sql
    assert "GRANT SELECT ON TABLE" in " ".join(sql.split())
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql


def test_migration_ownership_tracks_new_tables_and_dependency() -> None:
    ownership = json.loads(
        (_ROOT / "service-migrations/ownership.json").read_text(encoding="utf-8")
    )

    for table in (
        "cost_governance_analytics_run_receipt",
        "cost_governance_case_projection",
    ):
        assert table in ownership["table_migrations"]["core-control-plane"]
        assert table in ownership["whole_table_writers"]["core-control-plane"]
    dependency = next(
        item
        for item in ownership["migration_dependencies"]
        if item["consumer_revision"] == "operator_cost_governance_live_read_20260917"
    )
    assert dependency["provider_revision"] == "core_cost_governance_live_20260917"
