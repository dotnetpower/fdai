"""Disposable PostgreSQL evidence for explicit graph storage transitions."""

from __future__ import annotations

import runpy
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import patch

import psycopg
import pytest
from fdai.delivery.persistence import postgres_ontology
from fdai.delivery.persistence.postgres_ontology_transition import (
    activate_versioned_graph,
    materialize_legacy_graph,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
)
from psycopg import sql

from tests.persistence.test_postgres_ontology_instance import (
    REPO_ROOT,
    _isolated_replacement_store,
    _review_object,
    _writer_fence_sql,
)

pytestmark = pytest.mark.integration


async def _install(connection):
    await connection.execute(_writer_fence_sql()["INSTALL_SQL"])
    migration = runpy.run_path(
        str(
            REPO_ROOT / "service-migrations/branches/"
            "core-control-plane/versions/20260921_core_ontology_versions.py"
        )
    )
    with patch("alembic.op.execute") as execute:
        migration["upgrade"]()
        execute.assert_called_once()
        await connection.execute(execute.call_args.args[0])


@pytest.mark.parametrize("rollback_transaction", [False, True])
async def test_activation_and_materialization_preserve_graph(rollback_transaction):
    async with _isolated_replacement_store() as store:
        await store.replace_subgraph(
            objects=(_review_object("case"), _review_object("check", "ReviewCheck")),
            links=(OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check"),),
        )
        before = await store.query_objects()
        async with await store._connect() as connection:
            await _install(connection)
        async with await store._connect() as connection:
            digest = await activate_versioned_graph(connection)
            assert digest.startswith("sha256:")
            if rollback_transaction:
                await connection.rollback()
        assert await store.query_objects() == before
        if not rollback_transaction:
            async with await store._connect() as connection:
                with pytest.raises(psycopg.Error):
                    await connection.execute("DELETE FROM ontology_resource_legacy WHERE FALSE")
            async with await store._connect() as connection:
                await materialize_legacy_graph(connection)
            assert await store.query_objects() == before
        await store.create_object_if_absent(_review_object("later"))
        assert await store.get_object("later") is not None


async def test_identical_versioned_replacement_preserves_pointer_and_epoch():
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT * FROM ontology_graph_control")
            before = await cursor.fetchone()
        await store.replace_subgraph(
            objects=(replace(_review_object("case"), revision=1),), links=()
        )
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT * FROM ontology_graph_control")
            assert await cursor.fetchone() == before
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            assert (await cursor.fetchone())["count"] == 1


async def test_current_writer_mutations_and_materialization_use_latest_version():
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        await store.create_object_if_absent(_review_object("check", "ReviewCheck"))
        await store.upsert_link(
            OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check")
        )
        await store.upsert_object(_review_object("case"), expected_revision=1)
        before = await store.query_objects()
        assert len(before.links) == 1
        assert (await store.get_object("case")).revision == 2
        async with await store._connect() as connection:
            await materialize_legacy_graph(connection)
        assert await store.query_objects() == before
        assert await store.delete_object("check")
        assert not (await store.query_objects()).links


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE ontology_resource_version SET properties=properties",
        "DELETE FROM ontology_resource_version",
        "INSERT INTO ontology_resource_version SELECT * FROM ontology_resource_version",
        "UPDATE ontology_link_version SET properties=properties",
        "DELETE FROM ontology_link_version",
        "INSERT INTO ontology_link_version SELECT * FROM ontology_link_version",
        "TRUNCATE ontology_resource_version CASCADE",
        "TRUNCATE ontology_link_version",
        "UPDATE ontology_graph_version SET sealed=FALSE",
        "UPDATE ontology_graph_version SET content_digest=NULL",
    ],
)
async def test_sealed_version_rejects_mutation(mutation):
    async with _isolated_replacement_store() as store:
        await store.replace_subgraph(
            objects=(_review_object("case"), _review_object("check", "ReviewCheck")),
            links=(OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check"),),
        )
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        before = await store.query_objects()
        async with await store._connect() as connection:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                await connection.execute(mutation)
        assert await store.query_objects() == before


@pytest.mark.parametrize(
    "unsupported",
    ["view", "rls", "column_grant", "boolean_barrier", "trigger", "composite_fk", "link_fk"],
)
async def test_activation_refuses_unreviewed_access_or_dependencies(unsupported):
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            if unsupported == "view":
                await connection.execute(
                    "CREATE VIEW retained_reader AS SELECT * FROM ontology_resource"
                )
            elif unsupported == "rls":
                await connection.execute("ALTER TABLE ontology_resource ENABLE ROW LEVEL SECURITY")
            elif unsupported == "column_grant":
                await connection.execute("GRANT SELECT (id) ON ontology_resource TO PUBLIC")
            elif unsupported == "trigger":
                await connection.execute(
                    "CREATE FUNCTION custom_graph_side_effect() RETURNS trigger "
                    "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$; "
                    "CREATE TRIGGER custom_graph_side_effect BEFORE INSERT ON ontology_resource "
                    "FOR EACH ROW EXECUTE FUNCTION custom_graph_side_effect()"
                )
            elif unsupported == "composite_fk":
                await connection.execute(
                    "ALTER TABLE ontology_resource ADD UNIQUE (object_type,id);"
                    "CREATE TABLE retained_reference (kind TEXT, resource_id TEXT, "
                    "FOREIGN KEY (kind,resource_id) REFERENCES ontology_resource(object_type,id))"
                )
            elif unsupported == "link_fk":
                await connection.execute(
                    "CREATE TABLE retained_link_reference (source TEXT,kind TEXT,target TEXT,"
                    "FOREIGN KEY (source,kind,target) "
                    "REFERENCES ontology_link(from_id,link_type,to_id))"
                )
            else:
                await connection.execute(
                    "UPDATE state_kv SET value=jsonb_set(value,"
                    "'{minimum_writer_version}','true') WHERE key='ontology:writer-protocol'"
                )
        async with await store._connect() as connection:
            with pytest.raises(ValueError, match="migration|barrier"):
                await activate_versioned_graph(connection)
        assert (await store.get_object("case")).revision == 1
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT active_version FROM ontology_graph_control")
            assert (await cursor.fetchone())["active_version"] is None


async def test_version_publication_rejects_concurrent_base_change(monkeypatch):
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        finish = postgres_ontology.finish_versioned_write
        changed = False

        async def concurrent_finish(connection, write):
            nonlocal changed
            if not changed:
                changed = True
                await store.upsert_object(_review_object("concurrent"))
            await finish(connection, write)

        monkeypatch.setattr(postgres_ontology, "finish_versioned_write", concurrent_finish)
        with pytest.raises(OntologyInstanceValidationError, match="base or ownership epoch"):
            await store.upsert_object(_review_object("rejected"))
        assert await store.get_object("concurrent") is not None
        assert await store.get_object("rejected") is None
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            assert (await cursor.fetchone())["count"] == 2


async def test_version_publication_rolls_back_when_state_write_fails():
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation');"
                "ALTER TABLE state_kv ADD CHECK (key <> 'example:reject')"
            )
            await activate_versioned_graph(connection)
        before = await store.query_objects()
        with pytest.raises(psycopg.errors.CheckViolation):
            await store.replace_subgraph_with_state(
                objects=(
                    replace(
                        _review_object("case"),
                        revision=1,
                        properties={"id": "case", "status": "changed"},
                    ),
                ),
                links=(),
                previous_object_ids=("case",),
                previous_link_keys=(),
                state_updates={"example:reject": {"complete": True}},
                expected_active_generation="example-generation",
            )
        assert await store.query_objects() == before
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            assert (await cursor.fetchone())["count"] == 2


async def test_versioned_preparation_does_not_lock_active_generation_before_publication(
    monkeypatch,
):
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await activate_versioned_graph(connection)
        before = await store.query_objects()
        finish = postgres_ontology.finish_versioned_write

        async def advance_generation(connection, write):
            async with await store._connect() as other:
                await other.execute("SET LOCAL statement_timeout=500")
                await other.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_001,))
                await other.execute("UPDATE inventory_active SET snapshot_id='later-generation'")
            await finish(connection, write)

        monkeypatch.setattr(postgres_ontology, "finish_versioned_write", advance_generation)
        with pytest.raises(OntologyInstanceValidationError, match="no longer active"):
            await store.replace_subgraph_with_state(
                objects=(replace(_review_object("case"), revision=1),),
                links=(),
                previous_object_ids=("case",),
                previous_link_keys=(),
                state_updates={"example:status": {"complete": True}},
                expected_active_generation="example-generation",
            )
        assert await store.query_objects() == before


async def test_versioned_state_and_receipt_are_prepared_before_publication_lock(monkeypatch):
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await activate_versioned_graph(connection)
        finish = postgres_ontology.finish_versioned_write
        prepared = []

        async def inspect_preparation(connection, write):
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key='example:status'"
            )
            assert (await cursor.fetchone())["value"] == {"complete": True}
            async with await store._connect() as other:
                await other.execute("SET LOCAL statement_timeout=500")
                await other.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_001,))
                cursor = await other.execute(
                    "SELECT value FROM state_kv WHERE key='example:status'"
                )
                assert await cursor.fetchone() is None
            prepared.append(True)
            await finish(connection, write)

        monkeypatch.setattr(postgres_ontology, "finish_versioned_write", inspect_preparation)
        await store.replace_subgraph_with_state(
            objects=(replace(_review_object("case"), revision=1),),
            links=(),
            previous_object_ids=("case",),
            previous_link_keys=(),
            state_updates={"example:status": {"complete": True}},
            expected_active_generation="example-generation",
        )
        assert prepared == [True]


async def test_versioned_writer_preserves_external_foreign_keys():
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE retained_finding (resource_id TEXT REFERENCES ontology_resource(id))"
            )
            await activate_versioned_graph(connection)
        await store.upsert_object(_review_object("later"))
        async with await store._connect() as connection:
            await connection.execute("INSERT INTO retained_finding VALUES ('later')")
        with pytest.raises((psycopg.errors.ForeignKeyViolation, OntologyInstanceValidationError)):
            await store.delete_object("later")
        assert await store.get_object("later") is not None


async def test_version_retention_keeps_eight_and_preserves_inflight_reader():
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        async with await store._connect() as reader:
            await store._set_read_snapshot(reader)
            cursor = await reader.execute("SELECT revision FROM ontology_resource WHERE id='case'")
            assert (await cursor.fetchone())["revision"] == 1
            for revision in range(1, 12):
                await store.upsert_object(_review_object("case"), expected_revision=revision)
            cursor = await reader.execute("SELECT revision FROM ontology_resource WHERE id='case'")
            assert (await cursor.fetchone())["revision"] == 1
        assert (await store.get_object("case")).revision == 12
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            assert (await cursor.fetchone())["count"] == 8


@pytest.mark.parametrize(
    "condition", ["healthy", "empty", "pages", "truncated", "journal", "correction", "pressure"]
)
async def test_activated_resource_scans_preserve_evidence(monkeypatch, condition):
    from tests.persistence import test_postgres_ontology_instance as existing

    original = existing._isolated_committed_resource_store

    @asynccontextmanager
    async def activated(*args, **kwargs):
        async with original(*args, **kwargs) as pair:
            async with await pair[0]._connect() as connection:
                await _install(connection)
                await activate_versioned_graph(connection)
            yield pair

    monkeypatch.setattr(existing, "_isolated_committed_resource_store", activated)
    await existing.test_isolated_committed_resource_scan_preserves_current_evidence(
        condition, monkeypatch
    )
    if condition == "healthy":
        await existing.test_isolated_committed_resource_scan_keeps_gateway_authorization()


async def test_activation_preserves_reader_grants_without_inheriting_default_acl():
    role = "ontology_reader_" + uuid.uuid4().hex
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        try:
            async with await store._connect() as connection:
                await _install(connection)
                await connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
                cursor = await connection.execute("SELECT current_schema() AS schema")
                schema = (await cursor.fetchone())["schema"]
                await connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(role)
                    )
                )
                await connection.execute(
                    sql.SQL("GRANT SELECT ON ontology_resource TO {}").format(sql.Identifier(role))
                )
                await connection.execute(
                    "ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO PUBLIC"
                )
                await activate_versioned_graph(connection)
                await connection.execute(
                    "ALTER DEFAULT PRIVILEGES REVOKE SELECT ON TABLES FROM PUBLIC"
                )
            async with await store._connect() as connection:
                cursor = await connection.execute(
                    "SELECT 1 FROM pg_class AS relation CROSS JOIN LATERAL "
                    "aclexplode(relation.relacl) AS privilege "
                    "WHERE relation.oid='ontology_resource'::regclass "
                    "AND privilege.grantee=0"
                )
                assert await cursor.fetchone() is None
                await connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                cursor = await connection.execute("SELECT id FROM ontology_resource")
                assert (await cursor.fetchone())["id"] == "case"
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    await connection.execute("DELETE FROM ontology_resource WHERE FALSE")
        finally:
            async with await store._connect() as connection:
                await connection.execute(
                    "ALTER DEFAULT PRIVILEGES REVOKE SELECT ON TABLES FROM PUBLIC"
                )
                await connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                await connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


async def test_retention_pressure_rejects_new_version_until_cleanup(monkeypatch):
    from unittest.mock import AsyncMock

    from fdai.delivery.persistence.postgres_ontology_version_retention import prune_graph_versions

    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        monkeypatch.setattr(postgres_ontology, "prune_graph_versions", AsyncMock())
        for revision in range(1, 16):
            await store.upsert_object(_review_object("case"), expected_revision=revision)
        with pytest.raises(OntologyInstanceValidationError, match="retention is blocked"):
            await store.upsert_object(_review_object("case"), expected_revision=16)
        assert (await store.get_object("case")).revision == 16
        await prune_graph_versions(store._config)
        await store.upsert_object(_review_object("case"), expected_revision=16)
        assert (await store.get_object("case")).revision == 17


async def test_downgrade_requires_materialization_and_restores_legacy_writes():
    migration = runpy.run_path(
        str(
            REPO_ROOT / "service-migrations/branches/"
            "core-control-plane/versions/20260921_core_ontology_versions.py"
        )
    )
    with patch("alembic.op.execute") as execute:
        migration["downgrade"]()
        removal = execute.call_args.args[0]
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        async with await store._connect() as connection:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="materialize"):
                await connection.execute(removal)
        async with await store._connect() as connection:
            await materialize_legacy_graph(connection)
            await connection.execute(removal)
        await store.upsert_object(_review_object("case"), expected_revision=1)
        assert (await store.get_object("case")).revision == 2


async def test_service_role_can_write_versions_without_schema_owner():
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        try:
            async with await store._connect() as connection:
                await connection.execute("CREATE ROLE fdai_core")
                cursor = await connection.execute("SELECT current_schema() AS schema")
                schema = (await cursor.fetchone())["schema"]
                await connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO fdai_core").format(sql.Identifier(schema))
                )
                await connection.execute(
                    sql.SQL(
                        "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {} TO fdai_core"
                    ).format(sql.Identifier(schema))
                )
                await _install(connection)
                await activate_versioned_graph(connection)
            settings = conninfo_to_dict(store._config.dsn)
            role_dsn = make_conninfo(
                store._config.dsn, options=settings["options"] + " -c role=fdai_core"
            )
            writer = postgres_ontology.PostgresOntologyInstanceStore(
                config=replace(store._config, dsn=role_dsn),
                object_types=tuple(store._object_types.values()),
                link_types=tuple(store._link_types.values()),
            )
            await writer.upsert_object(_review_object("case"), expected_revision=1)
            await writer.create_object_if_absent(_review_object("check", "ReviewCheck"))
            await writer.upsert_link(
                OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check")
            )
            assert (await writer.get_object("case")).revision == 2
            assert await writer.delete_object("check")
        finally:
            async with await store._connect() as connection:
                cursor = await connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname='fdai_core'"
                )
                if await cursor.fetchone() is not None:
                    await connection.execute("DROP OWNED BY fdai_core; DROP ROLE fdai_core")


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM ontology_graph_control",
        "TRUNCATE ontology_graph_control",
        "UPDATE ontology_graph_control SET epoch=epoch+1",
    ],
)
async def test_graph_control_refuses_missing_or_unfenced_state(mutation):
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        async with await store._connect() as connection:
            await _install(connection)
            await activate_versioned_graph(connection)
        async with await store._connect() as connection:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                await connection.execute(mutation)
        assert await store.get_object("case") is not None


async def test_versioned_publication_capacity_measurement(monkeypatch, capsys):
    import hashlib
    import json

    from tests.persistence import test_postgres_ontology_instance as existing

    original = existing._isolated_replacement_store

    @asynccontextmanager
    async def activated():
        async with original() as store:
            async with await store._connect() as connection:
                await _install(connection)
                await activate_versioned_graph(connection)
            yield store

    monkeypatch.setattr(existing, "_isolated_replacement_store", activated)
    await existing.test_isolated_ontology_capacity_measurement(monkeypatch, "prepared")
    output = capsys.readouterr().out
    record = json.loads(
        next(
            line.partition("=")[2]
            for line in output.splitlines()
            if line.startswith("ONTOLOGY_CAPACITY=")
        )
    )
    record["publication"] = "versioned"
    root = REPO_ROOT / "services/core-control-plane/src/fdai/delivery/persistence"
    record["source_sha256"].update(
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "postgres_ontology_transition.py",
                "postgres_ontology_version_writer.py",
                "postgres_ontology_version_retention.py",
                "postgres_ontology_snapshot.py",
            )
        }
    )
    print("ONTOLOGY_CAPACITY=" + json.dumps(record, sort_keys=True))


@pytest.mark.parametrize("condition", ["none", "process_restart", "runtime_role", "reader_role"])
async def test_activated_cursor_repair_preserves_existing_boundaries(monkeypatch, condition):
    from tests.persistence import test_postgres_ontology_instance as existing

    original = existing._isolated_replacement_store

    @asynccontextmanager
    async def activated():
        async with original() as store:
            async with await store._connect() as connection:
                await _install(connection)
                await activate_versioned_graph(connection)
            yield store

    monkeypatch.setattr(existing, "_isolated_replacement_store", activated)
    await existing.test_isolated_cursor_repair_requires_exact_committed_graph(condition)


@pytest.mark.parametrize(
    "condition", ["resume", "base_changed", "expired", "tampered", "new_process"]
)
async def test_durable_graph_preparation_resumes_after_process_loss(monkeypatch, condition):
    from fdai.delivery.persistence import postgres_ontology_durable_preparation as durable_module

    class ProcessLost(BaseException):
        pass

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await activate_versioned_graph(connection)
        original = postgres_ontology.prepare_inventory_version

        async def interrupt(*args, **kwargs):
            await original(*args, **kwargs)
            raise ProcessLost

        monkeypatch.setattr(postgres_ontology, "prepare_inventory_version", interrupt)

        async def publish():
            await store.replace_subgraph_with_state(
                objects=(_review_object("case"),),
                links=(),
                previous_object_ids=(),
                previous_link_keys=(),
                state_updates={"example:state": {"complete": True}},
                expected_active_generation="example-generation",
            )

        with pytest.raises(ProcessLost):
            await publish()
        assert await store.get_object("case") is None
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE starts_with(key,'ontology-version-prepared:')"
            )
            retained = (await cursor.fetchone())["value"]
            if condition == "expired":
                await connection.execute(
                    "UPDATE state_kv SET updated_at=NOW()-INTERVAL '31 minutes' "
                    "WHERE starts_with(key,'ontology-version-prepared:')"
                )
            elif condition == "tampered":
                await connection.execute(
                    "UPDATE state_kv SET value=value || jsonb_build_object('base_epoch',42) "
                    "WHERE starts_with(key,'ontology-version-prepared:')"
                )
        if condition == "base_changed":
            await store.upsert_object(_review_object("other"))
        monkeypatch.setattr(postgres_ontology, "prepare_inventory_version", original)
        if condition == "new_process":
            import asyncio
            import os
            import sys

            code = """
import asyncio, os, runpy
from fdai.delivery.persistence import postgres_ontology_durable_preparation as preparation
fixture=runpy.run_path(os.environ['RESTART_TEST_FILE'])
async def forbid(*args,**kwargs):
    raise AssertionError('prepared graph must not be rebuilt')
preparation.replace_records=forbid
async def main():
    store=fixture['PostgresOntologyInstanceStore'](
        config=fixture['PostgresOntologyInstanceStoreConfig'](dsn=os.environ['RESTART_DSN']),
        object_types=(fixture['_type']('ReviewCase'),fixture['_type']('ReviewCheck')),
        link_types=(fixture['OntologyLinkType'](schema_version='1.0.0',name='contains_check',
            version='1.0.0',from_type='ReviewCase',to_type='ReviewCheck',
            cardinality=fixture['LinkCardinality'].ONE_TO_MANY),))
    await store.replace_subgraph_with_state(objects=(fixture['_review_object']('case'),),links=(),
        previous_object_ids=(),previous_link_keys=(),state_updates={'example:state':{'complete':True}},
        expected_active_generation='example-generation')
asyncio.run(main())
"""
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                env={
                    **os.environ,
                    "RESTART_DSN": store._config.dsn,
                    "RESTART_TEST_FILE": str(
                        REPO_ROOT
                        / "services/core-control-plane/tests/persistence"
                        / "test_postgres_ontology_instance.py"
                    ),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, errors = await asyncio.wait_for(process.communicate(), timeout=30)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, errors.decode().replace(
                store._config.dsn, "<disposable-dsn>"
            )
        elif condition in {"base_changed", "tampered"}:
            with pytest.raises(OntologyInstanceValidationError, match="base changed|invalid"):
                await publish()
            assert await store.get_object("case") is None
            return
        else:
            if condition == "resume":

                async def forbid(*args, **kwargs):
                    raise AssertionError("prepared graph must not be rebuilt")

                monkeypatch.setattr(durable_module, "replace_records", forbid)
            await publish()
        assert (await store.get_object("case")).revision == 1
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT active_version FROM ontology_graph_control")
            current = (await cursor.fetchone())["active_version"]
            assert (current == retained["version"]) is (condition != "expired")


async def test_completed_preparations_release_retention_pins():
    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await activate_versioned_graph(connection)
        for revision in range(18):
            await store.replace_subgraph_with_state(
                objects=(
                    replace(
                        _review_object("case"),
                        revision=revision,
                        properties={"id": "case", "status": str(revision)},
                    ),
                ),
                links=(),
                previous_object_ids=("case",) if revision else (),
                previous_link_keys=(),
                state_updates={"example:state": {"revision": revision}},
                expected_active_generation="example-generation",
            )
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            assert (await cursor.fetchone())["count"] == 8
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM state_kv "
                "WHERE starts_with(key,'ontology-version-prepared:')"
            )
            assert (await cursor.fetchone())["count"] == 0
