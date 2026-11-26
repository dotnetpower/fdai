"""Operator Cost Governance access and read-grant migration tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260828_operator_cost_governance.py"
)
READER = (
    REPO_ROOT / "services/operator-service/src/fdai_operator_service/postgres_cost_governance.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("operator_cost_governance_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_migration_owns_only_access_policy_tables() -> None:
    module = _load()
    assert module.migration_owner == "operator-service"
    assert module.owned_tables == ("cost_access_grant", "cost_disclosure_ceiling")
    assert module.down_revision == "operator_console_evidence_reads_20260827"


def test_operator_migration_grants_read_only_cost_evidence_access() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "GRANT SELECT ON TABLE" in source
    assert "vertical_package_activation" in source
    assert "cost_observation" in source
    assert "GRANT INSERT" not in source
    assert "GRANT UPDATE" not in source
    assert "GRANT DELETE" not in source


def test_downgrade_preserves_retained_core_cost_evidence() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()", 1)[1]
    assert "DROP TABLE cost_observation" not in downgrade
    assert "DROP TABLE vertical_package_activation" not in downgrade


def test_operator_reads_manager_derived_availability_without_digest_decision() -> None:
    source = READER.read_text(encoding="utf-8")

    assert "EXPECTED_ONTOLOGY_DIGEST" not in source
    assert "compatible=" not in source
    assert 'available=bool(row["available"])' in source
    assert "availability_reasons" in source
    assert "semantic_profile_digest" in source
