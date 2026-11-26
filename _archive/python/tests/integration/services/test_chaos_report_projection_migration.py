from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260921_operator_chaos_report_read.py"
)


def _migration_sql() -> tuple[dict[str, object], str]:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    return module, "\n".join(statements)


def test_operator_migration_exposes_only_bounded_chaos_observations() -> None:
    module, sql = _migration_sql()

    assert module["migration_owner"] == "operator-service"
    assert module["owned_tables"] == ()
    assert module["migration_prerequisites"] == {
        "service": "core-control-plane",
        "revision": "core_runtime_role_20260809",
    }
    assert "WITH (security_barrier = true)" in sql
    assert "CREATE VIEW operator_chaos_report_signal" in sql
    assert "kind = 'chaos'" in sql
    assert "category = 'workload'" in sql
    assert "GRANT SELECT ON TABLE operator_chaos_report_signal TO fdai_operator" in sql
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql


def test_migration_ownership_orders_core_report_signal_before_operator_view() -> None:
    ownership = json.loads(
        (_ROOT / "service-migrations/ownership.json").read_text(encoding="utf-8")
    )
    dependency = next(
        item
        for item in ownership["migration_dependencies"]
        if item["consumer_revision"] == "operator_chaos_report_read_20260921"
    )

    assert dependency == {
        "consumer_service": "operator-service",
        "consumer_revision": "operator_chaos_report_read_20260921",
        "provider_service": "core-control-plane",
        "provider_revision": "core_runtime_role_20260809",
        "schema_prerequisites": ["report_signal"],
        "provider_rollback": "blocked-until-operator-chaos-report-read-rollback",
    }
