"""Ontology release registry migration regressions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from fdai.shared.contracts.models import OntologyRelease

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATION = REPO_ROOT / "alembic/versions/20260813_0081_ontology_release_registry.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ontology_release_registry_migration", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ontology_release_registry_migration_seeds_durable_manifest() -> None:
    module = _load_migration()
    decoded = module._decode_release_seed()
    release = OntologyRelease.model_validate_json(decoded)

    assert len(decoded) == 28598
    assert release.digest == (
        "sha256:596873529ea6b479363fa34b07c326db02117726ac4d790f42a9abc707c6939d"
    )

    statements: list[str] = []
    connection = MagicMock()
    original_execute = module.op.execute
    original_get_bind = module.op.get_bind
    module.op.execute = statements.append
    module.op.get_bind = MagicMock(return_value=connection)
    try:
        module.upgrade()
    finally:
        module.op.execute = original_execute
        module.op.get_bind = original_get_bind

    assert module.revision == "20260813_0081"
    assert module.down_revision == "20260813_0080"
    assert len(statements) == 1
    statement = statements[0]
    assert "CREATE TABLE ontology_release" in statement
    assert "digest TEXT PRIMARY KEY" in statement
    assert "manifest JSONB NOT NULL" in statement
    assert "manifest ->> 'digest' = digest" in statement
    assert "jsonb_typeof(manifest -> 'declarations') = 'array'" in statement

    connection.execute.assert_called_once()
    insert_statement, params = connection.execute.call_args.args
    insert_sql = str(insert_statement)
    assert "INSERT INTO ontology_release (digest, manifest)" in insert_sql
    assert "VALUES (:digest, CAST(:manifest AS JSONB))" in insert_sql
    assert "ON CONFLICT (digest) DO NOTHING" in insert_sql
    assert params == {
        "digest": "sha256:596873529ea6b479363fa34b07c326db02117726ac4d790f42a9abc707c6939d",
        "manifest": decoded.decode("utf-8"),
    }
