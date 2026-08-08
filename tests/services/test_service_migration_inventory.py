from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
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
cli_module = importlib.import_module("service_migrations.cli")
schema_module = importlib.import_module("service_migrations.schema")

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
    future_tables = set(manifest.table_migrators) - tables
    assert tables <= set(manifest.table_migrators)
    assert future_tables == {
        "document_api_outbox",
        "document_worker_outbox",
        "executor_receipt_outbox",
    }
    assert set(manifest.table_writers) | transition_tables == set(manifest.table_migrators)
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


def test_forward_revision_rejects_ddl_for_an_unowned_table(tmp_path: Path) -> None:
    revision = tmp_path / "unowned_table.py"
    revision.write_text(
        "from alembic import op\n"
        "revision = 'next_revision'\n"
        "migration_owner = 'document-ingestion-api'\n"
        "owned_tables = ('document_version',)\n"
        "rollback = {'strategy': 'drop-column'}\n"
        "def upgrade():\n"
        "    op.add_column('audit_log', object())\n"
        "def downgrade():\n"
        "    pass\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="touches unowned tables.*audit_log"):
        inventory_module.load_revision_metadata(revision)


def test_forward_revision_rejects_dynamic_execute_without_provable_owner(
    tmp_path: Path,
) -> None:
    revision = tmp_path / "dynamic_execute.py"
    revision.write_text(
        "from alembic import op\n"
        "revision = 'next_revision'\n"
        "migration_owner = 'document-ingestion-api'\n"
        "owned_tables = ('document_version',)\n"
        "rollback = {'strategy': 'restore'}\n"
        "def upgrade():\n"
        "    statement = 'ALTER TABLE document_version ADD COLUMN unsafe int'\n"
        "    op.execute(statement)\n"
        "def downgrade():\n"
        "    pass\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"op\.execute\(\) SQL must be a string literal"):
        inventory_module.load_revision_metadata(revision)


def test_forward_revision_rejects_unowned_downgrade_ddl(tmp_path: Path) -> None:
    revision = tmp_path / "unowned_downgrade.py"
    revision.write_text(
        "from alembic import op\n"
        "revision = 'next_revision'\n"
        "migration_owner = 'document-ingestion-api'\n"
        "owned_tables = ('document_version',)\n"
        "rollback = {'strategy': 'restore'}\n"
        "def upgrade():\n"
        "    pass\n"
        "def downgrade():\n"
        "    op.drop_table('audit_log')\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="touches unowned tables.*audit_log"):
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
        config = Config(str(MIGRATION_ROOT / "configs" / f"{service_id}.ini"))
        expected_head = ScriptDirectory.from_config(config).get_current_head()
        assert expected_head is not None
        assert expected_head in result.stdout


def test_independent_service_manifest_references_existing_migration_branches() -> None:
    manifest = json.loads(
        (REPO_ROOT / "config" / "independent-services.json").read_text(encoding="utf-8")
    )
    services = manifest["services"]
    assert [service["target_migration_branch"] for service in services] == list(SERVICE_IDS)
    for service in services:
        assert (REPO_ROOT / service["target_terraform_root"] / "main.tf").is_file()
        assert (
            MIGRATION_ROOT / "branches" / service["target_migration_branch"] / "versions"
        ).is_dir()


def test_schema_contract_covers_exactly_five_services() -> None:
    contract = schema_module.load_schema_contract(MIGRATION_ROOT / "legacy-schema-contract.json")

    assert tuple(contract) == SERVICE_IDS
    assert all(value.digest.startswith("sha256:") for value in contract.values())
    assert all(value.table_count > 0 for value in contract.values())
    assert all(value.column_count >= value.table_count for value in contract.values())
    assert all(value.extensions for value in contract.values())


def test_adoption_evidence_requires_matching_schema_and_resolvable_reference(
    tmp_path: Path,
) -> None:
    schema_reference = tmp_path / "schema-snapshot.json"
    schema_reference.write_text("{}\n", encoding="utf-8")
    evidence = tmp_path / "adoption.json"
    digest = "sha256:" + "a" * 64
    evidence.write_text(
        json.dumps(
            {
                "service_id": "isolated-executor",
                "observed_legacy_head": "legacy-head",
                "observed_legacy_revision_count": 79,
                "observed_schema_fingerprint": digest,
                "verified_at": "2026-08-08T12:00:00+00:00",
                "schema_reference": schema_reference.name,
                "rollback_reference": "backup/example",
            }
        ),
        encoding="utf-8",
    )

    assert (
        cli_module._validate_evidence(
            evidence,
            service_id="isolated-executor",
            head="legacy-head",
            count=79,
            expected_schema_fingerprint=digest,
        )
        == "backup/example"
    )
    schema_reference.unlink()
    with pytest.raises(RuntimeError, match="schema_reference is not resolvable"):
        cli_module._validate_evidence(
            evidence,
            service_id="isolated-executor",
            head="legacy-head",
            count=79,
            expected_schema_fingerprint=digest,
        )


def test_rollback_evidence_requires_exact_head_timestamp_schema_and_reference(
    tmp_path: Path,
) -> None:
    persisted = tmp_path / "rollback-artifact.json"
    persisted.write_text("{}\n", encoding="utf-8")
    digest = "sha256:" + "b" * 64
    evidence: dict[str, object] = {
        "schema_version": 1,
        "service_id": "isolated-executor",
        "from_head": "executor_receipt_outbox_20260808",
        "resulting_head": "executor_base_20260808",
        "schema_fingerprint": digest,
        "completed_at": datetime.now(tz=UTC).isoformat(),
        "persisted_reference": str(persisted),
    }

    cli_module._validate_rollback_evidence(
        evidence,
        service_id="isolated-executor",
        from_head="executor_receipt_outbox_20260808",
        resulting_head="executor_base_20260808",
        schema_fingerprint=digest,
    )
    evidence["resulting_head"] = "wrong-head"
    with pytest.raises(RuntimeError, match="rollback evidence resulting_head"):
        cli_module._validate_rollback_evidence(
            evidence,
            service_id="isolated-executor",
            from_head="executor_receipt_outbox_20260808",
            resulting_head="executor_base_20260808",
            schema_fingerprint=digest,
        )


def test_service_sql_writers_and_outbox_paths_match_ownership_manifest() -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    ownership = ownership_module.load_ownership_manifest(
        MIGRATION_ROOT / "ownership.json",
        inventory,
    )
    api_postgres = (
        REPO_ROOT
        / "services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/postgres.py"
    ).read_text(encoding="utf-8")
    api_deletion = (
        REPO_ROOT / "services/document-ingestion-api/src/fdai_ingestion_api_service/deletion.py"
    ).read_text(encoding="utf-8")
    api_ingestion = (
        REPO_ROOT / "services/document-ingestion-api/src/fdai_ingestion_api_service/ingestion.py"
    ).read_text(encoding="utf-8")
    worker_postgres = (
        REPO_ROOT
        / "services/document-processing-worker/src"
        / "fdai_document_worker_service/adapters/postgres.py"
    ).read_text(encoding="utf-8")
    worker_activity = (
        REPO_ROOT
        / "services/document-processing-worker/src"
        / "fdai_document_worker_service/adapters/activity.py"
    ).read_text(encoding="utf-8")
    worker_processing = (
        REPO_ROOT
        / "services/document-processing-worker/src/fdai_document_worker_service/processing.py"
    ).read_text(encoding="utf-8")
    executor_idempotency = (
        REPO_ROOT
        / "services/isolated-executor/src/fdai_executor_service/adapters/postgres_idempotency.py"
    ).read_text(encoding="utf-8")

    assert "INSERT INTO audit_log" not in api_postgres
    assert "INSERT INTO audit_log" not in worker_activity
    assert "knowledge_chunk" not in api_deletion
    assert ".publish(" not in api_ingestion
    assert ".publish(" not in api_deletion
    assert ".publish(" not in worker_processing
    assert "CREATE TABLE" not in executor_idempotency.upper()
    assert "document_api_outbox" in api_postgres
    assert "document_worker_outbox" in worker_postgres
    assert "FOR UPDATE SKIP LOCKED" in api_postgres
    assert "next_attempt_at = clock_timestamp() + INTERVAL '5 seconds'" in api_postgres
    assert "FOR UPDATE SKIP LOCKED" in worker_activity
    assert "next_attempt_at = clock_timestamp() + INTERVAL '5 seconds'" in worker_activity
    assert api_postgres.index("self._publisher.publish") < api_postgres.index(
        "self._mark_published"
    )
    assert worker_activity.index("self._event_bus.publish") < worker_activity.index(
        "self._mark_published"
    )
    assert "AND state = %s AND revision = %s" in api_postgres
    assert "AND state = %s AND revision = %s" in worker_postgres
    assert "SET active = FALSE, revision = revision + 1" in api_postgres
    assert "SET active = FALSE, revision = revision + 1" in worker_postgres
    audit_scopes = {
        (transition.writer, transition.scope)
        for transition in ownership.transitions
        if transition.table == "audit_log"
    }
    assert audit_scopes == {
        ("core-control-plane", "entries:saga-owned-control-plane"),
        ("isolated-executor", "entries:executor-pre-effect-terminal"),
    }
