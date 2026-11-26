from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260828_core_cost_governance_runtime.py"
)
_STORE = (
    _ROOT
    / "services/core-control-plane/src/fdai/delivery/persistence"
    / "postgres_cost_governance.py"
)


def test_cost_governance_tables_are_core_owned_and_least_privileged() -> None:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    sql = "\n".join(statements)

    assert module["migration_owner"] == "core-control-plane"
    assert set(module["owned_tables"]) == {
        "vertical_package_activation",
        "cost_observation",
        "cost_collection_cursor",
    }
    assert "GRANT SELECT, INSERT ON TABLE cost_observation TO fdai_core" in " ".join(sql.split())
    assert "UPDATE ON TABLE cost_observation" not in sql
    assert "DELETE" not in sql
    assert "FROM PUBLIC, fdai_core" in sql

    ownership = json.loads(
        (_ROOT / "service-migrations/ownership.json").read_text(encoding="utf-8")
    )
    core_tables = set(ownership["table_migrations"]["core-control-plane"])
    assert set(module["owned_tables"]) <= core_tables


def test_cost_cursor_has_independent_collection_and_analysis_cas() -> None:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    sql = "\n".join(statements)

    assert "revision BIGINT NOT NULL DEFAULT 0" in sql
    assert "analysis_revision BIGINT NOT NULL DEFAULT 0" in sql
    assert "last_published_observation_id TEXT NULL" in sql
    assert "previously_enabled BOOLEAN NOT NULL DEFAULT FALSE" in sql


def test_activation_persists_independent_availability_and_artifact_attribution() -> None:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    sql = "\n".join(statements)

    assert "available BOOLEAN NOT NULL," in sql
    assert "available BOOLEAN NOT NULL DEFAULT" not in sql
    assert "CHECK (NOT enabled OR available)" in sql
    assert "availability_reasons JSONB NOT NULL" in sql
    assert "jsonb_array_length(availability_reasons) <= 32" in sql
    for column in (
        "package_version TEXT NOT NULL",
        "image_digest TEXT NOT NULL",
        "asset_manifest_digest TEXT NOT NULL",
        "semantic_profile_digest TEXT NOT NULL",
        "ontology_release_digest TEXT NOT NULL",
    ):
        assert column in sql

    store = _STORE.read_text(encoding="utf-8")
    for field in (
        "activation.available",
        "activation.availability_reasons",
        "activation.package_version",
        "activation.image_digest",
        "activation.asset_manifest_digest",
        "activation.semantic_profile_digest",
    ):
        assert field in store
