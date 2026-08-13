"""Ontology release registry migration regressions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATION = REPO_ROOT / "alembic/versions/20260813_0081_ontology_release_registry.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ontology_release_registry_migration", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ontology_release_registry_migration_declares_durable_manifest_constraints() -> None:
    module = _load_migration()
    statements: list[str] = []
    original_execute = module.op.execute
    module.op.execute = statements.append
    try:
        module.upgrade()
    finally:
        module.op.execute = original_execute

    assert module.revision == "20260813_0081"
    assert module.down_revision == "20260813_0080"
    assert len(statements) == 1
    statement = statements[0]
    assert "CREATE TABLE ontology_release" in statement
    assert "digest TEXT PRIMARY KEY" in statement
    assert "manifest JSONB NOT NULL" in statement
    assert "manifest ->> 'digest' = digest" in statement
    assert "jsonb_typeof(manifest -> 'declarations') = 'array'" in statement
