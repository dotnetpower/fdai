"""Forward rename metadata and ownership checks without a database."""

from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_ROOT = REPO_ROOT / "service-migrations"
sys.path.insert(0, str(MIGRATION_ROOT))
inventory_module = importlib.import_module("service_migrations.inventory")
ownership_module = importlib.import_module("service_migrations.ownership")
validation_module = importlib.import_module("service_migrations.validation")
INVENTORY_MIGRATION = (
    MIGRATION_ROOT / "branches/core-control-plane/versions/"
    "20261030_core_inventory_storage_efficiency.py"
)


@pytest.fixture
def migration_workspace():
    directory = REPO_ROOT / ".fdai" / "migration-rename-tests" / uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _migration(directory, body, *, owned=("source", "target")):
    path = directory / "rename.py"
    path.write_text(
        "from alembic import op\n"
        "revision='rename_revision'\n"
        "migration_owner='core-control-plane'\n"
        f"owned_tables={owned!r}\n"
        "rollback={'strategy':'rename-back','restores':'previous','requires':'writers-stopped'}\n"
        "def upgrade():\n"
        + "\n".join(f"    {line}" for line in body.splitlines())
        + "\ndef downgrade():\n    pass\n",
        encoding="utf-8",
    )
    return inventory_module.load_revision_metadata(path)


def _legacy(*names):
    return inventory_module.LegacyInventory(
        down_revisions={"baseline": None},
        table_sources={name: ("baseline",) for name in names},
    )


@pytest.mark.parametrize(
    "body",
    [
        'op.execute("ALTER TABLE source RENAME TO target;")',
        'op.execute("ALTER TABLE public.source RENAME TO public.target;")',
        'op.rename_table("source", "target")',
        'op.rename_table(old_table_name="source", new_table_name="target", schema="public")',
    ],
)
def test_rename_registers_both_identities_but_does_not_claim_a_new_table_create(
    migration_workspace, body
):
    metadata = _migration(migration_workspace, body)
    assert metadata.renamed_tables == (("source", "target"),)
    assert metadata.touched_tables == ("source", "target")
    assert metadata.created_tables == ()
    assert validation_module._validate_forward_renames([metadata], _legacy("source")) == {"target"}


@pytest.mark.parametrize("missing", ["source", "target"])
@pytest.mark.parametrize(
    "body",
    [
        'op.execute("ALTER TABLE source RENAME TO target;")',
        'op.rename_table("source", "target")',
    ],
)
def test_rename_requires_source_and_target_in_declared_ownership(
    migration_workspace, missing, body
):
    owned = tuple(name for name in ("source", "target") if name != missing)
    with pytest.raises(ValueError, match=f"touches unowned tables.*{missing}"):
        _migration(migration_workspace, body, owned=owned)


@pytest.mark.parametrize(
    "body",
    [
        'op.rename_table(source, "target")',
        'op.rename_table("source", target)',
        'op.rename_table("source", "target", schema="other_schema")',
        'op.execute("ALTER TABLE other_schema.source RENAME TO target;")',
        'op.execute("ALTER TABLE source RENAME TO other_schema.target;")',
    ],
)
def test_rename_rejects_dynamic_or_unreviewed_namespace_names(migration_workspace, body):
    with pytest.raises(ValueError):
        _migration(migration_workspace, body)


def test_rename_requires_an_existing_table_source(migration_workspace):
    metadata = _migration(migration_workspace, 'op.execute("ALTER TABLE source RENAME TO target;")')
    with pytest.raises(ValueError, match="rename source is not an available table: source"):
        validation_module._validate_forward_renames([metadata], _legacy())


def test_rename_rejects_an_existing_table_target(migration_workspace):
    metadata = _migration(migration_workspace, 'op.execute("ALTER TABLE source RENAME TO target;")')
    with pytest.raises(ValueError, match="rename target already exists: target"):
        validation_module._validate_forward_renames([metadata], _legacy("source", "target"))


@pytest.mark.parametrize(
    "body",
    [
        'op.execute("CREATE VIEW target AS SELECT * FROM source; '
        'ALTER TABLE source RENAME TO target;")',
        'op.execute("CREATE MATERIALIZED VIEW target AS SELECT * FROM source; '
        'ALTER TABLE source RENAME TO target;")',
    ],
)
def test_rename_rejects_a_view_target_in_the_same_namespace(migration_workspace, body):
    metadata = _migration(migration_workspace, body)
    with pytest.raises(ValueError, match="rename target already exists: target"):
        validation_module._validate_forward_renames([metadata], _legacy("source"))


def test_table_rename_cannot_reuse_the_compatibility_view_as_a_table_source(migration_workspace):
    metadata = _migration(
        migration_workspace,
        'op.execute("ALTER TABLE source RENAME TO target; '
        "CREATE VIEW source AS SELECT * FROM target; "
        'ALTER TABLE source RENAME TO other;")',
        owned=("source", "target", "other"),
    )
    with pytest.raises(ValueError, match="rename source is not an available table: source"):
        validation_module._validate_forward_renames([metadata], _legacy("source"))


def test_idempotent_table_create_cannot_reclassify_an_existing_view(migration_workspace):
    metadata = _migration(
        migration_workspace,
        'op.execute("CREATE VIEW source AS SELECT 1; '
        "CREATE TABLE IF NOT EXISTS source(id TEXT); "
        'ALTER TABLE source RENAME TO target;")',
    )
    with pytest.raises(ValueError, match="relation kind collision before rename: source"):
        validation_module._validate_forward_renames([metadata], _legacy())


def test_mixed_sql_and_alembic_rename_chain_preserves_statement_order(migration_workspace):
    metadata = _migration(
        migration_workspace,
        'op.execute("CREATE TABLE source(id TEXT); ALTER TABLE source RENAME TO middle;")\n'
        'op.rename_table("middle", "target")\n'
        'op.execute("CREATE VIEW source AS SELECT * FROM target;")',
        owned=("source", "middle", "target"),
    )
    assert metadata.renamed_tables == (("source", "middle"), ("middle", "target"))
    assert metadata.created_views == ("source",)
    assert validation_module._validate_forward_renames([metadata], _legacy()) == {
        "middle",
        "target",
    }


def test_duplicate_rename_source_and_target_collisions_fail_closed(migration_workspace):
    metadata = _migration(
        migration_workspace,
        'op.execute("ALTER TABLE source RENAME TO target; ALTER TABLE other RENAME TO target;")',
        owned=("source", "target", "other"),
    )
    with pytest.raises(ValueError, match="rename target already exists: target"):
        validation_module._validate_forward_renames([metadata], _legacy("source", "other"))


def test_dropped_rename_source_is_not_treated_as_existing(migration_workspace):
    metadata = _migration(
        migration_workspace,
        'op.execute("DROP TABLE source; ALTER TABLE source RENAME TO target;")',
    )
    with pytest.raises(ValueError, match="rename source is not an available table: source"):
        validation_module._validate_forward_renames([metadata], _legacy("source"))


def test_noop_rename_is_not_an_introduced_identity(migration_workspace):
    with pytest.raises(ValueError, match="requires distinct source and target"):
        _migration(
            migration_workspace,
            'op.execute("ALTER TABLE source RENAME TO source;")',
        )


@pytest.mark.parametrize(
    "identity", ["inventory_snapshot_resource", "inventory_snapshot_resource_row"]
)
def test_coordinator_rejects_cross_service_ownership_of_either_rename_end(identity):
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic/versions")
    ownership = ownership_module.load_ownership_manifest(
        MIGRATION_ROOT / "ownership.json", inventory
    )
    changed = replace(
        ownership, table_migrators={**ownership.table_migrators, identity: "operator-service"}
    )
    with pytest.raises(ValueError, match=f"{identity} belongs to migration owner operator-service"):
        validation_module.validate_service_branches(MIGRATION_ROOT, inventory, changed)


def test_inventory_logical_views_and_new_physical_identities_keep_the_core_owner():
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic/versions")
    ownership = ownership_module.load_ownership_manifest(
        MIGRATION_ROOT / "ownership.json", inventory
    )
    metadata = inventory_module.load_revision_metadata(INVENTORY_MIGRATION)
    assert metadata.created_views == (
        "inventory_observation_snapshot_member",
        "inventory_snapshot_link",
        "inventory_snapshot_resource",
    )
    assert len(metadata.renamed_tables) == 3
    assert len(metadata.created_tables) == 4
    for relation in metadata.owned_tables:
        assert ownership.table_migrators[relation] == "core-control-plane"
        assert ownership.table_writers[relation] == "core-control-plane"
    assert (
        len(validation_module.validate_service_branches(MIGRATION_ROOT, inventory, ownership)) == 5
    )
