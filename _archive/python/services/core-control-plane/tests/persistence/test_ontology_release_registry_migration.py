"""Ontology release registry migration regressions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from fdai.shared.contracts.models import OntologyRelease

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATION = REPO_ROOT / "alembic/versions/20260813_0081_ontology_release_registry.py"
HISTORICAL_MIGRATION = REPO_ROOT / "alembic/versions/20260817_0085_historical_ontology_release.py"


def _load_migration(path: Path = MIGRATION) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"ontology_release_registry_migration_{path.stem}", path
    )
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


def test_historical_ontology_release_migration_backfills_exact_manifest() -> None:
    base_module = _load_migration()
    module = _load_migration(HISTORICAL_MIGRATION)
    base_release = OntologyRelease.model_validate_json(base_module._decode_release_seed())
    base_manifest = base_release.model_dump(mode="json")
    decoded = module._build_historical_manifest(base_manifest)
    release = OntologyRelease.model_validate_json(decoded)

    assert len(decoded) == 27670
    assert release.digest == (
        "sha256:13f0dbf8ca4420df10aa730e2e1701ad2f22fa57da059b2a8181e4a9073ae349"
    )
    assert sum(item.kind.value == "object" for item in release.declarations) == 73
    assert sum(item.kind.value == "link" for item in release.declarations) == 103
    assert all(item.kind.value in {"object", "link"} for item in release.declarations)

    select_result = MagicMock()
    select_result.scalar_one.return_value = base_manifest
    connection = MagicMock()
    connection.execute.return_value = select_result
    execute_operation = MagicMock()
    original_execute = module.op.execute
    original_get_bind = module.op.get_bind
    module.op.execute = execute_operation
    module.op.get_bind = MagicMock(return_value=connection)
    try:
        module.upgrade()
        module.downgrade()
    finally:
        module.op.execute = original_execute
        module.op.get_bind = original_get_bind

    assert module.revision == "20260817_0085"
    assert module.down_revision == "20260814_0084"
    assert connection.execute.call_count == 2

    select_statement, select_params = connection.execute.call_args_list[0].args
    assert "SELECT manifest FROM ontology_release WHERE digest = :digest" in str(select_statement)
    assert select_params == {"digest": base_release.digest}

    insert_statement, insert_params = connection.execute.call_args_list[1].args
    insert_sql = str(insert_statement)
    assert "INSERT INTO ontology_release (digest, manifest)" in insert_sql
    assert "ON CONFLICT (digest) DO NOTHING" in insert_sql
    assert insert_params == {
        "digest": release.digest,
        "manifest": decoded.decode("utf-8"),
    }

    execute_operation.assert_called_once()
    (delete_statement,) = execute_operation.call_args.args
    delete_sql = str(delete_statement)
    assert "DELETE FROM ontology_release AS release" in delete_sql
    assert "SELECT 1 FROM ontology_resource" in delete_sql
    assert "SELECT 1 FROM ontology_link" in delete_sql
    assert delete_statement.compile().params == {"digest": release.digest}
