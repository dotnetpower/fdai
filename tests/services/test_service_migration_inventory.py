from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_ROOT = REPO_ROOT / "service-migrations"
sys.path.insert(0, str(MIGRATION_ROOT))

inventory_module = importlib.import_module("service_migrations.inventory")
ownership_module = importlib.import_module("service_migrations.ownership")
adoption_module = importlib.import_module("service_migrations.adoption")
validation_module = importlib.import_module("service_migrations.validation")

SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)


def test_legacy_migration_inventory_is_linear_and_complete() -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")

    assert len(inventory.down_revisions) == 79
    assert inventory.heads == ("20260806_0077",)
    assert len(inventory.table_sources) == 100
    assert "IF" not in inventory.table_sources
    assert inventory.table_sources["document_worker_claim"] == ("20260806_0075",)
    assert inventory.table_sources["case_history_migration_state"] == (
        "20260723_0054",
        "20260723_0055",
    )


def test_every_legacy_table_has_one_migrator_and_one_write_contract() -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    manifest = ownership_module.load_ownership_manifest(
        MIGRATION_ROOT / "ownership.json",
        inventory,
    )

    tables = set(inventory.table_sources)
    transition_tables = {transition.table for transition in manifest.transitions}
    assert set(manifest.table_migrators) == tables
    assert set(manifest.table_writers) | transition_tables == tables
    assert not set(manifest.table_writers) & transition_tables
    assert len({(item.table, item.scope) for item in manifest.transitions}) == len(
        manifest.transitions
    )
    assert {item.writer for item in manifest.transitions} == set(SERVICE_IDS)


def test_ownership_manifest_rejects_overlapping_migrators(tmp_path: Path) -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    raw = json.loads((MIGRATION_ROOT / "ownership.json").read_text(encoding="utf-8"))
    raw["table_migrations"]["operator-service"].append("audit_log")
    conflicting = tmp_path / "ownership.json"
    conflicting.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="overlapping table_migrations ownership"):
        ownership_module.load_ownership_manifest(conflicting, inventory)


def test_five_configs_have_distinct_heads_and_explicit_adoption() -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    ownership = ownership_module.load_ownership_manifest(
        MIGRATION_ROOT / "ownership.json",
        inventory,
    )
    adoptions = validation_module.validate_service_branches(
        MIGRATION_ROOT,
        inventory,
        ownership,
    )

    heads: set[str] = set()
    version_tables: set[str] = set()
    for service_id in SERVICE_IDS:
        config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
        service_heads = ScriptDirectory.from_config(config).get_heads()
        assert len(service_heads) == 1
        heads.update(service_heads)
        adoption = adoptions[service_id]
        assert adoption.required_legacy_head == inventory.heads[0]
        assert adoption.rollback_strategy == "delete-service-version-row"
        version_tables.add(adoption.service_version_table)
    assert len(heads) == 5
    assert len(version_tables) == 5


def test_forward_revision_requires_rollback_metadata(tmp_path: Path) -> None:
    revision = tmp_path / "missing_rollback.py"
    revision.write_text(
        "revision = 'next_revision'\n"
        "migration_owner = 'core-control-plane'\n"
        "owned_tables = ('audit_log',)\n"
        "rollback = None\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rollback metadata is required"):
        inventory_module.load_revision_metadata(revision)


def test_dispatcher_validates_all_and_refuses_unknown_service() -> None:
    valid = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, str(MIGRATION_ROOT / "migrate.py"), "all", "validate"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr
    assert "validated 5 service migration branch(es)" in valid.stdout

    unknown = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, str(MIGRATION_ROOT / "migrate.py"), "unknown", "heads"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert unknown.returncode == 2
    assert "unknown service" in unknown.stderr


def test_service_command_wrappers_exist_and_are_executable() -> None:
    for service_id in SERVICE_IDS:
        wrapper = MIGRATION_ROOT / "bin" / service_id
        assert wrapper.is_file()
        assert wrapper.stat().st_mode & 0o111
        environment = dict(os.environ, FDAI_MIGRATION_PYTHON=sys.executable)
        result = subprocess.run(  # noqa: S603 - fixed repository wrapper
            [str(wrapper), "heads"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert result.returncode == 0, result.stderr
        assert "base_20260808" in result.stdout
