"""Offline checks on the alembic migration modules.

No database is touched. Verifies:

- Each migration file imports without error.
- ``upgrade`` / ``downgrade`` are defined.
- ``revision`` and ``down_revision`` are consistent (linear chain).
- Migrations use raw SQL only (no SQLAlchemy metadata reference) - the
  runtime StateStore adapter will be psycopg-only, so any ORM-flavoured
  migration would drift.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "alembic" / "versions"

MIGRATION_FILES = sorted(p for p in MIGRATIONS_DIR.glob("*.py") if not p.name.startswith("__"))


def _load_migration(path: Path) -> ModuleType:
    """Load a migration file directly - ``alembic/`` is a script folder, not a package."""
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", MIGRATION_FILES)
def test_migration_module_is_importable(path: Path) -> None:
    module = _load_migration(path)
    assert callable(getattr(module, "upgrade", None)), f"{path.name}: upgrade missing"
    assert callable(getattr(module, "downgrade", None)), f"{path.name}: downgrade missing"
    assert isinstance(module.revision, str)
    assert module.down_revision is None or isinstance(module.down_revision, str)
    assert f"_{module.revision}_" in f"_{path.stem}_", (
        f"{path.name}: filename does not match revision {module.revision}"
    )


def test_migration_chain_is_linear() -> None:
    """The set of revision ids equals the set of down_revision + None values."""
    revisions: dict[str, str | None] = {}
    for path in MIGRATION_FILES:
        module = _load_migration(path)
        assert module.revision not in revisions, f"duplicate revision id: {module.revision}"
        revisions[module.revision] = module.down_revision

    parents = {parent for parent in revisions.values() if parent is not None}
    heads = set(revisions.keys()) - parents
    assert len(heads) == 1, f"expected one head, got {heads}"

    for rev, parent in revisions.items():
        if parent is not None:
            assert parent in revisions, f"{rev}: parent {parent} not found"


def test_materialized_operator_memory_proposal_has_foreign_key() -> None:
    migration = (MIGRATIONS_DIR / "20260803_0070_operator_memory_proposal_fk.py").read_text(
        encoding="utf-8"
    )

    assert 'down_revision: str | None = "20260801_0069"' in migration
    assert "FOREIGN KEY (materialized_entry_id)" in migration
    assert "REFERENCES operator_memory(id)" in migration
    assert "ON DELETE RESTRICT" in migration
    assert "VALIDATE CONSTRAINT" in migration


def test_ontology_direction_migration_invalidates_only_reversed_links() -> None:
    migration = (MIGRATIONS_DIR / "20260808_0078_ontology_link_direction.py").read_text(
        encoding="utf-8"
    )

    assert 'down_revision: str | None = "20260806_0077"' in migration
    assert "type_version = '1.0.0' OR type_version IS NULL" in migration
    assert "source.properties ->> 'type' = 'compute.vm'" in migration
    assert "sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037" in migration
    assert "WHERE catalog_digest =" in migration
    assert "WHERE type_version IS NOT NULL OR catalog_digest IS NOT NULL" not in migration
    assert "cardinality = 'one_to_many'" in migration
    assert "ontology_link_contains_version_direction" in migration
    assert "type_version IS NOT NULL AND type_version <> '1.0.0'" in migration
    assert "DROP CONSTRAINT IF EXISTS ontology_link_contains_version_direction" in migration


def test_ontology_direction_guard_repairs_existing_0078_databases() -> None:
    migration = (MIGRATIONS_DIR / "20260808_0079_ontology_direction_guard.py").read_text(
        encoding="utf-8"
    )

    assert 'down_revision: str | None = "20260808_0078"' in migration
    assert "type_version = '1.0.0' OR type_version IS NULL" in migration
    assert "ontology_link_contains_version_direction" in migration
    assert "IF NOT EXISTS" in migration
    assert "DROP CONSTRAINT IF EXISTS" in migration


@pytest.mark.parametrize("path", MIGRATION_FILES)
def test_migration_uses_raw_sql_only(path: Path) -> None:
    """Migrations MUST NOT import SQLAlchemy ORM types (Column, Table, MetaData)."""
    text = path.read_text(encoding="utf-8")
    forbidden = ("sa.Column", "sa.Table(", "sa.MetaData(", "declarative_base")
    for token in forbidden:
        assert token not in text, f"{path.name}: forbidden ORM token {token!r}"
    assert re.search(r"\bop\.execute\(", text), (
        f"{path.name}: no op.execute() call - likely empty migration"
    )
