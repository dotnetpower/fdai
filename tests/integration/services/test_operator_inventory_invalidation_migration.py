"""Operator inventory-invalidation read-grant migration tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260906_operator_inventory_invalidation_read.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "operator_inventory_invalidation_read_migration",
        MIGRATION,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_migration_owns_no_new_tables() -> None:
    module = _load()
    assert module.migration_owner == "operator-service"
    assert module.owned_tables == ()
    assert module.down_revision == "operator_handover_document_read_20260905"


def test_operator_migration_grants_select_only_journal_access() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

    assert "GRANT SELECT ON TABLE inventory_observation_journal TO fdai_operator" in upgrade
    assert "GRANT INSERT" not in upgrade
    assert "GRANT UPDATE" not in upgrade
    assert "GRANT DELETE" not in upgrade
    assert "REVOKE ALL PRIVILEGES ON TABLE inventory_observation_journal" in upgrade
    assert "PUBLIC" in upgrade


def test_operator_migration_downgrade_revokes_without_dropping_the_journal() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()", 1)[1]

    assert "REVOKE ALL PRIVILEGES ON TABLE inventory_observation_journal FROM fdai_operator" in (
        downgrade
    )
    assert "DROP TABLE" not in downgrade
    assert "DROP FUNCTION" not in downgrade


def test_operator_migration_never_touches_a_different_table() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert source.count("inventory_observation_journal") == 3
    assert "inventory_observation_pending_tombstone" not in source
    assert "inventory_snapshot" not in source
