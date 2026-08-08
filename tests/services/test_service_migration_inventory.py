from __future__ import annotations

import importlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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

    assert len(inventory.down_revisions) == 81
    assert inventory.heads == ("20260808_0079",)
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
        "document_worker_effect",
        "document_worker_outbox",
        "executor_receipt_outbox",
    }
    assert set(manifest.table_writers) | transition_tables == set(manifest.table_migrators)
    assert not set(manifest.table_writers) & transition_tables
    assert len({(item.table, item.scope) for item in manifest.transitions}) == len(
        manifest.transitions
    )
    assert {item.writer for item in manifest.transitions} == set(SERVICE_IDS)
    transition_scopes = {
        item.transition_id: (item.writer, item.scope) for item in manifest.transitions
    }
    api_scope = (
        "document-ingestion-api",
        "transitions:created->uploading,uploading->received,uploading->held,nondeleted->deleting",
    )
    worker_scope = (
        "document-processing-worker",
        "transitions:received->quarantined,quarantined->scanning,"
        "scanning->protection_check,protection_check->extracting|ready|held,"
        "extracting->indexing|failed,indexing->ready|ready_with_warnings|failed,"
        "deleting->deleted",
    )
    assert transition_scopes["document-upload-api-lifecycle"] == api_scope
    assert transition_scopes["document-version-api-lifecycle"] == api_scope
    assert transition_scopes["document-upload-worker-lifecycle"] == worker_scope
    assert transition_scopes["document-version-worker-lifecycle"] == worker_scope

    dependencies = {
        (item.consumer_service, item.consumer_revision): item
        for item in manifest.migration_dependencies
    }
    assert dependencies[("isolated-executor", "executor_runtime_role_20260808")].provider == (
        "core-control-plane",
        "core_shared_data_ownership_20260808",
    )
    worker_dependency = dependencies[
        ("document-processing-worker", "document_worker_outbox_20260808")
    ]
    assert worker_dependency.provider == (
        "document-ingestion-api",
        "ingestion_api_outbox_20260808",
    )
    ordered = ownership_module.migration_order(manifest, SERVICE_IDS)
    assert ordered.index("core-control-plane") < ordered.index("isolated-executor")
    assert ordered.index("document-ingestion-api") < ordered.index("document-processing-worker")


def test_ownership_manifest_rejects_overlapping_migrators(tmp_path: Path) -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    raw = json.loads((MIGRATION_ROOT / "ownership.json").read_text(encoding="utf-8"))
    raw["table_migrations"]["operator-service"].append("audit_log")
    conflicting = tmp_path / "ownership.json"
    conflicting.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="overlapping table_migrations ownership"):
        ownership_module.load_ownership_manifest(conflicting, inventory)


def test_ownership_manifest_rejects_cyclic_migration_dependencies(tmp_path: Path) -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    raw = json.loads((MIGRATION_ROOT / "ownership.json").read_text(encoding="utf-8"))
    raw["migration_dependencies"].append(
        {
            "consumer_service": "core-control-plane",
            "consumer_revision": "core_shared_data_ownership_20260808",
            "provider_service": "isolated-executor",
            "provider_revision": "executor_runtime_role_20260808",
            "schema_prerequisites": ["executor_state_namespace"],
            "provider_rollback": "blocked-until-core-baseline",
        }
    )
    conflicting = tmp_path / "ownership.json"
    conflicting.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="migration dependency cycle"):
        ownership_module.load_ownership_manifest(conflicting, inventory)


def test_branch_validation_rejects_unknown_dependency_revision(tmp_path: Path) -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    raw = json.loads((MIGRATION_ROOT / "ownership.json").read_text(encoding="utf-8"))
    raw["migration_dependencies"][0]["provider_revision"] = "missing_provider_revision"
    invalid = tmp_path / "ownership.json"
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    ownership = ownership_module.load_ownership_manifest(invalid, inventory)

    with pytest.raises(ValueError, match="dependency provider revision is absent"):
        validation_module.validate_service_branches(MIGRATION_ROOT, inventory, ownership)


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


def test_service_migrations_serialize_cross_service_ddl_before_service_lock() -> None:
    environment_source = (MIGRATION_ROOT / "runtime/env.py").read_text(encoding="utf-8")
    cli_source = (MIGRATION_ROOT / "service_migrations/cli.py").read_text(encoding="utf-8")

    assert 'coordination_lock_key = _lock_key("all-services")' in environment_source
    coordination_lock = environment_source.index('{"lock_key": coordination_lock_key}')
    service_lock = environment_source.index('{"lock_key": migration_lock_key}')
    migration_run = environment_source.index("context.run_migrations()", service_lock)
    assert coordination_lock < service_lock < migration_run
    assert 'text("SELECT pg_advisory_lock(:lock_key)")' in cli_source
    assert 'config.attributes["connection"] = connection' in cli_source
    dependency_check = cli_source.index(
        "_require_dependency_revisions(", cli_source.index("def _upgrade_service")
    )
    command_upgrade = cli_source.index("command.upgrade(config, revision, sql=False)")
    assert dependency_check < command_upgrade
    dependent_check = cli_source.index(
        "_require_dependents_at_baseline(",
        cli_source.index("def _downgrade_service"),
    )
    command_downgrade = cli_source.index("command.downgrade(config, revision)")
    assert dependent_check < command_downgrade


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


def test_document_worker_declares_lifecycle_schema_prerequisite() -> None:
    raw = json.loads((MIGRATION_ROOT / "ownership.json").read_text(encoding="utf-8"))
    dependencies = {
        (item["consumer_service"], item["consumer_revision"]): item
        for item in raw["migration_dependencies"]
    }
    assert dependencies[("document-processing-worker", "document_worker_outbox_20260808")] == {
        "consumer_service": "document-processing-worker",
        "consumer_revision": "document_worker_outbox_20260808",
        "provider_service": "document-ingestion-api",
        "provider_revision": "ingestion_api_outbox_20260808",
        "schema_prerequisites": [
            "document_upload_session.revision",
            "document_version.revision",
        ],
        "provider_rollback": "blocked-until-consumer-baseline",
    }

    revision_path = (
        MIGRATION_ROOT
        / "branches/document-processing-worker/versions/20260808_document_worker_outbox.py"
    )
    migration = runpy.run_path(str(revision_path))
    assert migration["migration_prerequisites"] == {
        "revision": "ingestion_api_outbox_20260808",
        "columns": (
            "document_upload_session.revision",
            "document_version.revision",
        ),
    }

    class MissingPrerequisiteOp:
        @staticmethod
        def get_bind() -> object:
            return object()

        @staticmethod
        def create_table(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("worker outbox DDL ran before prerequisite validation")

    fake_sa = SimpleNamespace(
        inspect=lambda _bind: SimpleNamespace(get_columns=lambda _table: ({"name": "id"},))
    )
    upgrade = migration["upgrade"]
    upgrade.__globals__["op"] = MissingPrerequisiteOp()
    upgrade.__globals__["sa"] = fake_sa
    with pytest.raises(RuntimeError, match="ingestion_api_outbox_20260808"):
        upgrade()


def test_ingestion_api_downgrade_rejects_deployed_worker_dependency() -> None:
    revision_path = (
        MIGRATION_ROOT
        / "branches/document-ingestion-api/versions/20260808_ingestion_api_lifecycle_outbox.py"
    )
    migration = runpy.run_path(str(revision_path))
    assert migration["rollback"] == {
        "strategy": "drop-api-outbox-and-revision-columns-after-worker-baseline",
        "restores": "ingestion_api_base_20260808",
        "requires": "document_worker_base_20260808",
    }

    class WorkerHeadResult:
        @staticmethod
        def scalar_one_or_none() -> str:
            return "document_worker_outbox_20260808"

    class UnsafeDowngradeOp:
        dropped: list[str] = []

        @staticmethod
        def get_bind() -> SimpleNamespace:
            return SimpleNamespace(execute=lambda _statement: WorkerHeadResult())

        @classmethod
        def drop_table(cls, table: str) -> None:
            cls.dropped.append(table)

        @classmethod
        def drop_column(cls, table: str, column: str) -> None:
            cls.dropped.append(f"{table}.{column}")

        @staticmethod
        def execute(_statement: str) -> None:
            raise AssertionError("downgrade DML ran before dependency validation")

    downgrade = migration["downgrade"]
    downgrade.__globals__["op"] = UnsafeDowngradeOp()
    downgrade.__globals__["sa"] = SimpleNamespace(text=lambda statement: statement)
    with pytest.raises(RuntimeError, match="document-processing-worker"):
        downgrade()
    assert UnsafeDowngradeOp.dropped == []


def test_executor_runtime_role_is_guarded_and_least_privileged() -> None:
    raw = json.loads((MIGRATION_ROOT / "ownership.json").read_text(encoding="utf-8"))
    dependencies = {
        (item["consumer_service"], item["consumer_revision"]): item
        for item in raw["migration_dependencies"]
    }
    assert dependencies[("isolated-executor", "executor_runtime_role_20260808")] == {
        "consumer_service": "isolated-executor",
        "consumer_revision": "executor_runtime_role_20260808",
        "provider_service": "core-control-plane",
        "provider_revision": "core_shared_data_ownership_20260808",
        "schema_prerequisites": ["state_kv_namespace_owner", "audit_log.seq"],
        "provider_rollback": "blocked-until-executor-baseline",
    }
    source = (
        MIGRATION_ROOT / "branches/isolated-executor/versions/20260808_executor_runtime_role.py"
    ).read_text(encoding="utf-8")

    assert "CREATE ROLE fdai_executor" in source
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in source
    assert "NOINHERIT NOREPLICATION NOBYPASSRLS" in source
    assert "FROM PUBLIC, fdai_executor" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE state_kv TO fdai_executor" in source
    assert "GRANT SELECT, INSERT ON TABLE audit_log TO fdai_executor" in source
    assert "GRANT SELECT, INSERT ON TABLE action_idempotency TO fdai_executor" in source
    assert (
        "GRANT SELECT, INSERT, UPDATE ON TABLE executor_receipt_outbox TO fdai_executor" in source
    )
    assert "current_user = 'fdai_executor'" in source
    assert "starts_with(source_key, 'isolated-executor:')" in source
    assert "starts_with(target_key, 'isolated-executor:')" in source
    assert "GRANT UPDATE, DELETE ON TABLE audit_log" not in source


def test_operator_runtime_role_is_reproducible_and_exact() -> None:
    source = (
        MIGRATION_ROOT / "branches/operator-service/versions/20260808_operator_runtime_role.py"
    ).read_text(encoding="utf-8")

    assert "CREATE ROLE fdai_operator" in source
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in source
    assert "NOINHERIT NOREPLICATION NOBYPASSRLS" in source
    assert "ALTER ROLE fdai_operator" in source
    assert "FROM PUBLIC, fdai_operator" in source
    assert "GRANT SELECT ON TABLE audit_log TO fdai_operator" in source
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE state_kv TO fdai_operator" in source
    assert "REVOKE CREATE ON SCHEMA public FROM fdai_operator" in source
    assert "GRANT INSERT, UPDATE, DELETE ON TABLE audit_log" not in source
    assert "GRANT DELETE ON TABLE state_kv" not in source


def test_worker_migration_widens_claim_check_and_blocks_inflight_deletion() -> None:
    revision_path = (
        MIGRATION_ROOT
        / "branches/document-processing-worker/versions/20260808_document_worker_outbox.py"
    )
    source = revision_path.read_text(encoding="utf-8")
    migration = runpy.run_path(str(revision_path))

    assert "'deletion'" in source
    assert "document_worker_claim_stage_check" in source

    class DeletionClaimResult:
        @staticmethod
        def scalar_one() -> int:
            return 1

    class UnsafeDowngradeOp:
        changed: list[str] = []
        results = iter((0, 1))

        @staticmethod
        def get_bind() -> SimpleNamespace:
            return SimpleNamespace(
                execute=lambda _statement: SimpleNamespace(
                    scalar_one=lambda: next(UnsafeDowngradeOp.results)
                )
            )

        @classmethod
        def drop_table(cls, table: str) -> None:
            cls.changed.append(table)

        @classmethod
        def drop_constraint(cls, name: str, table: str, **_kwargs: object) -> None:
            cls.changed.append(f"{table}.{name}")

    downgrade = migration["downgrade"]
    downgrade.__globals__["op"] = UnsafeDowngradeOp()
    downgrade.__globals__["sa"] = SimpleNamespace(text=lambda statement: statement)
    with pytest.raises(RuntimeError, match="in-flight deletion claims"):
        downgrade()
    assert UnsafeDowngradeOp.changed == []
    assert "status <> 'completed'" in source


def test_worker_claim_check_downgrade_removes_completed_deletion_rows() -> None:
    revision_path = (
        MIGRATION_ROOT
        / "branches/document-processing-worker/versions/20260808_document_worker_outbox.py"
    )
    migration = runpy.run_path(str(revision_path))

    class SafeDowngradeOp:
        statements: list[str] = []

        @staticmethod
        def get_bind() -> SimpleNamespace:
            return SimpleNamespace(execute=lambda _statement: SimpleNamespace(scalar_one=lambda: 0))

        @classmethod
        def execute(cls, statement: str) -> None:
            cls.statements.append(statement)

        @staticmethod
        def drop_table(_table: str) -> None:
            return None

        @staticmethod
        def drop_constraint(_name: str, _table: str, **_kwargs: object) -> None:
            return None

        @staticmethod
        def create_check_constraint(*_args: object, **_kwargs: object) -> None:
            return None

    downgrade = migration["downgrade"]
    downgrade.__globals__["op"] = SafeDowngradeOp()
    downgrade.__globals__["sa"] = SimpleNamespace(text=lambda statement: statement)

    downgrade()

    assert any(
        "DELETE FROM document_worker_claim" in statement and "status = 'completed'" in statement
        for statement in SafeDowngradeOp.statements
    )


@pytest.mark.parametrize(
    ("relative_path", "error_match"),
    (
        (
            "branches/document-ingestion-api/versions/20260808_ingestion_api_lifecycle_outbox.py",
            "document-ingestion-api downgrade is blocked while unpublished outbox rows exist",
        ),
        (
            "branches/document-processing-worker/versions/20260808_document_worker_outbox.py",
            "document-processing-worker downgrade is blocked while unpublished outbox rows exist",
        ),
        (
            "branches/isolated-executor/versions/20260808_executor_receipt_outbox.py",
            "isolated-executor downgrade is blocked while unpublished outbox rows exist",
        ),
    ),
)
def test_outbox_downgrades_reject_unpublished_rows(
    relative_path: str,
    error_match: str,
) -> None:
    migration = runpy.run_path(str(MIGRATION_ROOT / relative_path))

    class PendingResult:
        @staticmethod
        def scalar_one() -> int:
            return 1

        @staticmethod
        def scalar_one_or_none() -> str:
            return "document_worker_base_20260808"

    class GuardedConnection:
        statements: list[str] = []

        @classmethod
        def execute(cls, statement: object) -> PendingResult:
            cls.statements.append(str(statement))
            return PendingResult()

    class GuardedOp:
        changed: list[str] = []

        @staticmethod
        def get_bind() -> type[GuardedConnection]:
            return GuardedConnection

        @classmethod
        def execute(cls, statement: str) -> None:
            cls.changed.append(statement)

        @classmethod
        def drop_table(cls, table: str) -> None:
            cls.changed.append(table)

    downgrade = migration["downgrade"]
    downgrade.__globals__["op"] = GuardedOp()
    downgrade.__globals__["sa"] = SimpleNamespace(text=lambda statement: statement)

    with pytest.raises(RuntimeError, match=error_match):
        downgrade()
    assert GuardedOp.changed == []
    lock_index = next(
        index
        for index, statement in enumerate(GuardedConnection.statements)
        if "ACCESS EXCLUSIVE" in statement
    )
    count_index = next(
        index
        for index, statement in enumerate(GuardedConnection.statements)
        if "SELECT count(*)" in statement
    )
    assert lock_index < count_index


def test_executor_role_downgrade_locks_outbox_before_drain_check() -> None:
    source = (
        MIGRATION_ROOT / "branches/isolated-executor/versions/20260808_executor_runtime_role.py"
    ).read_text(encoding="utf-8")

    lock_index = source.index("LOCK TABLE executor_receipt_outbox IN ACCESS EXCLUSIVE MODE")
    count_index = source.index("SELECT count(*) FROM executor_receipt_outbox")
    assert lock_index < count_index


def test_ingestion_outboxes_declare_runtime_least_privilege() -> None:
    api_source = (
        MIGRATION_ROOT
        / "branches/document-ingestion-api/versions/20260808_ingestion_api_lifecycle_outbox.py"
    ).read_text(encoding="utf-8")
    worker_source = (
        MIGRATION_ROOT
        / "branches/document-processing-worker/versions/20260808_document_worker_outbox.py"
    ).read_text(encoding="utf-8")
    effect_source = (
        MIGRATION_ROOT
        / "branches/document-processing-worker/versions/20260808_document_worker_effects.py"
    ).read_text(encoding="utf-8")

    assert "GRANT SELECT, INSERT, UPDATE ON TABLE document_api_outbox" in api_source
    assert "FROM PUBLIC, fdai_ingestion_worker" in api_source
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE document_worker_outbox" in worker_source
    assert "FROM PUBLIC, fdai_ingestion_api" in worker_source
    assert "REVOKE ALL PRIVILEGES ON TABLE document_api_outbox" in api_source
    assert "REVOKE ALL PRIVILEGES ON TABLE document_worker_outbox" in worker_source
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE document_worker_effect" in effect_source
    assert "FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost" in effect_source


def test_lifecycle_migration_enforces_role_owned_transitions_in_database() -> None:
    source = (
        MIGRATION_ROOT
        / "branches/document-ingestion-api/versions/20260808_ingestion_api_lifecycle_outbox.py"
    ).read_text(encoding="utf-8")

    assert "CREATE FUNCTION enforce_document_lifecycle_transition_owner" in source
    assert "CREATE TRIGGER document_upload_session_transition_owner" in source
    assert "CREATE TRIGGER document_version_transition_owner" in source
    assert "current_user = 'fdai_ingestion_api'" in source
    assert "current_user = 'fdai_ingestion_worker'" in source
    assert "OLD.state = 'uploading' AND NEW.state IN ('received', 'held')" in source
    assert "OLD.state = 'received' AND NEW.state = 'quarantined'" in source
    assert "OLD.state = 'deleting' AND NEW.state = 'deleted'" in source
    assert "NEW.revision <> OLD.revision + 1" in source


def test_shared_storage_migrations_enforce_canonical_writer_role_matrix() -> None:
    inventory = inventory_module.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    ownership = ownership_module.load_ownership_manifest(
        MIGRATION_ROOT / "ownership.json",
        inventory,
    )
    core_path = (
        MIGRATION_ROOT
        / "branches/core-control-plane/versions/20260808_core_shared_data_ownership.py"
    )
    worker_path = (
        MIGRATION_ROOT
        / "branches/document-processing-worker/versions/20260808_worker_knowledge_ownership.py"
    )
    api_stewardship_source = (
        REPO_ROOT
        / "services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/stewardship.py"
    ).read_text(encoding="utf-8")
    worker_handover_source = (
        REPO_ROOT
        / "services/document-processing-worker/src"
        / "fdai_document_worker_service/adapters/handover.py"
    ).read_text(encoding="utf-8")

    class CaptureOp:
        statements: list[str] = []

        @classmethod
        def execute(cls, statement: str) -> None:
            cls.statements.append(statement)

    core_migration = runpy.run_path(str(core_path))
    core_migration["upgrade"].__globals__["op"] = CaptureOp()
    core_migration["upgrade"]()
    core_sql = "\n".join(CaptureOp.statements)

    CaptureOp.statements = []
    worker_migration = runpy.run_path(str(worker_path))
    worker_migration["upgrade"].__globals__["op"] = CaptureOp()
    worker_migration["upgrade"]()
    worker_sql = "\n".join(CaptureOp.statements)

    transition_writers = {
        table: {
            transition.writer for transition in ownership.transitions if transition.table == table
        }
        for table in ("audit_log", "state_kv")
    }
    assert transition_writers == {
        "audit_log": {"core-control-plane", "isolated-executor"},
        "state_kv": {
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
        },
    }
    assert ownership.table_writers["knowledge_chunk"] == "document-processing-worker"
    state_scopes = {
        transition.writer: transition.scope
        for transition in ownership.transitions
        if transition.table == "state_kv"
    }
    assert state_scopes["document-ingestion-api"] == (
        "namespaces:stewardship_merge:*,stewardship_repository_draft:*"
    )
    assert state_scopes["document-processing-worker"] == "namespace:handover_draft:*"
    assert 'f"stewardship_merge:' in api_stewardship_source
    assert 'f"stewardship_repository_draft:' in api_stewardship_source
    assert 'f"handover_draft:' in worker_handover_source
    assert "CREATE FUNCTION enforce_state_kv_namespace_owner" in core_sql
    assert "CREATE TRIGGER state_kv_namespace_owner" in core_sql
    assert "starts_with(target_key, 'stewardship_merge:')" in core_sql
    assert "starts_with(target_key, 'stewardship_repository_draft:')" in core_sql
    assert "starts_with(target_key, 'handover_draft:')" in core_sql
    assert "source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END" in core_sql
    assert "starts_with(source_key, 'stewardship_merge:')" in core_sql
    assert "starts_with(source_key, 'stewardship_repository_draft:')" in core_sql
    assert "starts_with(source_key, 'handover_draft:')" in core_sql
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE state_kv "
        "TO fdai_ingestion_api, fdai_ingestion_worker" in core_sql
    )
    assert "GRANT SELECT ON TABLE state_kv TO fdai_ingestion_cohost" in core_sql
    assert "REVOKE INSERT, UPDATE, DELETE ON TABLE audit_log" in core_sql
    assert "GRANT SELECT ON TABLE audit_log" in core_sql
    assert "GRANT SELECT, INSERT ON TABLE audit_log" not in core_sql
    assert "REVOKE ALL PRIVILEGES ON TABLE knowledge_chunk" in worker_sql
    assert "GRANT SELECT ON TABLE knowledge_chunk TO fdai_ingestion_api" in worker_sql
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE knowledge_chunk "
        "TO fdai_ingestion_worker" in worker_sql
    )
    assert "GRANT SELECT, DELETE ON TABLE knowledge_chunk TO fdai_ingestion_api" not in (
        core_sql + worker_sql
    )


@pytest.mark.parametrize(
    ("relative_path", "error_match", "required_head", "requires", "risk"),
    (
        (
            "branches/core-control-plane/versions/20260808_core_shared_data_ownership.py",
            "core shared-data downgrade requires stopped ingestion runtimes",
            "ingestion_api_base_20260808",
            "api-worker-base-heads-shared-database-drained-and-explicit-stop-ack",
            "restores-overbroad-legacy-grants-for-monolith-recovery-only",
        ),
        (
            "branches/document-processing-worker/versions/20260808_worker_knowledge_ownership.py",
            "worker knowledge downgrade requires stopped ingestion runtimes",
            "ingestion_api_outbox_20260808",
            "api-outbox-worker-knowledge-heads-shared-database-drained-and-explicit-stop-ack",
            "restores-api-delete-and-cohost-write-for-monolith-recovery-only",
        ),
    ),
)
def test_shared_storage_downgrades_fail_closed_before_restoring_legacy_grants(
    relative_path: str,
    error_match: str,
    required_head: str,
    requires: str,
    risk: str,
) -> None:
    migration = runpy.run_path(str(MIGRATION_ROOT / relative_path))
    assert migration["rollback"] == {
        "strategy": "restore-legacy-grants-after-dependent-runtime-stop",
        "restores": migration["down_revision"],
        "requires": requires,
        "risk": risk,
    }
    guard_sql = str(migration["_DEPENDENT_RUNTIME_GUARD"])
    assert "fdai.dependent_runtimes_stopped" in guard_sql
    assert "pg_stat_activity" in guard_sql
    assert "datname = current_database()" in guard_sql
    assert required_head in guard_sql

    class UnsafeGuardResult:
        @staticmethod
        def scalar_one() -> bool:
            return False

    class UnsafeDowngradeOp:
        statements: list[str] = []

        @staticmethod
        def get_bind() -> SimpleNamespace:
            return SimpleNamespace(execute=lambda _statement: UnsafeGuardResult())

        @classmethod
        def execute(cls, statement: str) -> None:
            cls.statements.append(statement)

    downgrade = migration["downgrade"]
    downgrade.__globals__["op"] = UnsafeDowngradeOp()
    with pytest.raises(RuntimeError, match=error_match):
        downgrade()
    assert UnsafeDowngradeOp.statements == []


def test_core_namespace_downgrade_requires_executor_dependency_at_baseline() -> None:
    migration = runpy.run_path(
        str(
            MIGRATION_ROOT
            / "branches/core-control-plane/versions/20260808_core_shared_data_ownership.py"
        )
    )
    guard_sql = str(migration["_DEPENDENT_RUNTIME_GUARD"])

    assert "alembic_version_isolated_executor" in guard_sql
    assert "executor_base_20260808" in guard_sql


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


def test_dispatcher_all_upgrade_uses_manifest_dependency_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def capture_upgrade(service_id: str, **_kwargs: object) -> None:
        calls.append(service_id)

    monkeypatch.setattr(cli_module, "_upgrade_service", capture_upgrade)

    assert cli_module.main(["all", "upgrade"]) == 0
    assert tuple(calls) == (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    )


def test_service_command_wrappers_exist_and_are_executable() -> None:
    for service_id in SERVICE_IDS:
        wrapper = MIGRATION_ROOT / "bin" / service_id
        assert wrapper.is_file()
        assert wrapper.stat().st_mode & 0o111
        environment = dict(os.environ)
        environment.pop("FDAI_MIGRATION_PYTHON", None)
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


def test_service_command_wrapper_fails_clearly_without_project_python(
    tmp_path: Path,
) -> None:
    wrapper_root = tmp_path / "repo" / "service-migrations" / "bin"
    wrapper_root.mkdir(parents=True)
    wrapper = wrapper_root / "core-control-plane"
    shutil.copy2(MIGRATION_ROOT / "bin" / "core-control-plane", wrapper)
    shell = shutil.which("sh")
    assert shell is not None
    path = tmp_path / "path"
    path.mkdir()
    (path / "sh").symlink_to(shell)
    environment = {"PATH": str(path)}

    result = subprocess.run(  # noqa: S603 - isolated repository wrapper fixture
        [str(wrapper), "heads"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 127
    assert result.stderr == (
        "error: no supported project Python found; set FDAI_MIGRATION_PYTHON, "
        "create .venv, or install uv\n"
    )


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
                "observed_legacy_revision_count": 81,
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
            count=81,
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
            count=81,
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
    assert api_postgres.index("self._publisher.publish(physical_topic") < api_postgres.index(
        "self._mark_published(event.event_id)"
    )
    assert worker_activity.index(
        "self._event_bus.publish(self._event_topic"
    ) < worker_activity.index("self._mark_published(event.event_id)")
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
