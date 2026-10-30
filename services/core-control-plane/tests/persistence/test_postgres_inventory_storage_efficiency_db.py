"""Serial-only storage/migration checks on the isolated loopback validation cluster."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.persistence.postgres_inventory_observation_write import append_records
from fdai.delivery.persistence.postgres_inventory_shared_membership import (
    canonical_json,
    content_digest,
)
from fdai.delivery.persistence.postgres_inventory_shared_properties import prune_shared_properties
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import (
    load_previous_snapshot_members,
    load_snapshot_generation_records,
    load_snapshot_history_records,
    store_snapshot_membership,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_support import stage_snapshot_batch
from fdai.shared.providers.inventory import InventoryBatch, LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import STATE_FACT_METADATA_PROPERTY
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from tests.persistence.test_postgres_inventory_storage_efficiency import (
    MIGRATION,
    NOW,
    migration_statements,
    records,
)

pytestmark = pytest.mark.integration
_BRANCH = "service-migrations/branches/core-control-plane/versions/"


@dataclass(frozen=True)
class StorageDatabase:
    dsn: str = field(repr=False)
    schema: str


async def apply_migration(connection, path: str, direction: str = "upgrade") -> None:
    _, statements = migration_statements(path, direction)
    for statement in statements:
        await connection.execute(statement)


@pytest.fixture
async def storage_database(request) -> AsyncIterator[StorageDatabase]:
    source = os.environ.get("FDAI_DATABASE_URL")
    if not source or os.environ.get("FDAI_SERVICE_MIGRATIONS_READY") != "1":
        pytest.skip("isolated service-migrated validation PostgreSQL is not configured")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parameters = conninfo_to_dict(source)
    assert parameters.get("host") in {"localhost", "127.0.0.1"}
    assert parameters.get("port") == "5433"
    schema = "inventory_storage_" + uuid4().hex
    async with await psycopg.AsyncConnection.connect(source, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        dsn = make_conninfo(source, options=f"-c search_path={schema},public")
        try:
            async with await psycopg.AsyncConnection.connect(
                dsn, row_factory=dict_row
            ) as connection:
                await apply_migration(
                    connection, "alembic/versions/20260714_0015_inventory_snapshots.py"
                )
                await connection.execute(
                    "CREATE TABLE inventory_observation_journal "
                    "(LIKE public.inventory_observation_journal INCLUDING ALL);"
                    "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());"
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON inventory_snapshot_resource, "
                    "inventory_snapshot_link TO fdai_core;"
                )
                await apply_migration(
                    connection, _BRANCH + "20261029_core_inventory_snapshot_membership.py"
                )
                if getattr(request, "param", None) != "legacy":
                    await apply_migration(connection, MIGRATION)
            yield StorageDatabase(dsn=dsn, schema=schema)
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("storage_database", ["legacy"], indirect=True)
@pytest.mark.parametrize(
    "relation",
    (
        "inventory_snapshot_resource",
        "inventory_snapshot_link",
        "inventory_observation_snapshot_member",
    ),
)
@pytest.mark.parametrize("materialized", [False, True])
async def test_migration_rejects_external_view_dependency_without_partial_ddl(
    storage_database, relation: str, materialized: bool
) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        command = (
            "CREATE MATERIALIZED VIEW external_inventory AS SELECT * FROM {} WITH NO DATA"
            if materialized
            else "CREATE VIEW external_inventory AS SELECT * FROM {}"
        )
        await connection.execute(sql.SQL(command).format(sql.Identifier(relation)))
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="inventory storage efficiency migration has unsupported view dependency",
        ):
            async with connection.transaction():
                await apply_migration(connection, MIGRATION)
        row = await (
            await connection.execute(
                "SELECT to_regclass(format('%%I.inventory_snapshot_properties', "
                "current_schema())) IS NULL AS unchanged, "
                "(SELECT relkind FROM pg_class WHERE oid=%s::regclass) AS original_kind",
                (relation,),
            )
        ).fetchone()
        assert row == {"unchanged": True, "original_kind": "r"}
        assert await (
            await connection.execute(
                "SELECT count(*) AS count FROM pg_class WHERE oid='external_inventory'::regclass"
            )
        ).fetchone() == {"count": 1}


@pytest.mark.parametrize("storage_database", ["legacy"], indirect=True)
async def test_migration_lock_wait_is_finite_and_failure_is_atomic(storage_database) -> None:
    async with (
        await psycopg.AsyncConnection.connect(storage_database.dsn) as blocker,
        await psycopg.AsyncConnection.connect(
            storage_database.dsn, row_factory=dict_row
        ) as connection,
    ):
        await blocker.execute("LOCK TABLE inventory_snapshot_resource IN ACCESS SHARE MODE")
        await connection.execute("SET LOCAL lock_timeout='0'")
        started = time.monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            async with connection.transaction():
                await apply_migration(connection, MIGRATION)
        assert time.monotonic() - started < 10
        assert await (
            await connection.execute(
                "SELECT to_regclass(format('%I.inventory_snapshot_properties', "
                "current_schema())) IS NULL AS unchanged"
            )
        ).fetchone() == {"unchanged": True}


@pytest.mark.parametrize("storage_database", ["legacy"], indirect=True)
async def test_private_legacy_inventory_does_not_bind_modern_public_storage(
    storage_database,
) -> None:
    from fdai.delivery.persistence.postgres_inventory_shared_membership import (
        require_membership_namespace,
    )
    from fdai.delivery.persistence.postgres_inventory_shared_properties import share_property_rows

    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        public = await (
            await connection.execute(
                "SELECT to_regclass('public.inventory_snapshot_properties') "
                "IS NOT NULL AS available"
            )
        ).fetchone()
        if not public["available"]:
            pytest.skip("modern public inventory storage is required for the collision regression")
        before = await (
            await connection.execute(
                "SELECT count(*) AS count FROM public.inventory_snapshot_properties"
            )
        ).fetchone()
        assert await prune_shared_properties(connection) == 0
        with pytest.raises(ValueError, match="logical inventory schema"):
            await share_property_rows(connection, [{"props": {"state": "running"}}])
        with pytest.raises(ValueError, match="logical inventory schema"):
            await require_membership_namespace(connection)
        assert (
            await (
                await connection.execute(
                    "SELECT count(*) AS count FROM public.inventory_snapshot_properties"
                )
            ).fetchone()
            == before
        )


async def test_shared_helpers_are_invoker_and_ignore_caller_temp_shadow(storage_database) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        observations = records("pinned-source", count=1)
        await save_generation(connection, observations, watermark=0)
        schema = (await (await connection.execute("SELECT current_schema() AS name")).fetchone())[
            "name"
        ]
        assert schema != "public"
        rows = await (
            await connection.execute(
                "SELECT prosecdef,proconfig FROM pg_proc WHERE pronamespace=%s::regnamespace "
                "AND proname=ANY(%s::text[])",
                (
                    schema,
                    [
                        "fdai_inventory_shared_snapshot_members",
                        "fdai_inventory_snapshot_resource_compat",
                        "fdai_inventory_snapshot_link_compat",
                    ],
                ),
            )
        ).fetchall()
        assert len(rows) == 3
        assert all(not row["prosecdef"] for row in rows)
        assert all(
            row["proconfig"] == [f"search_path=pg_catalog, {schema}, pg_temp"] for row in rows
        )
        await connection.execute("SET LOCAL search_path=public,pg_temp")
        public_caller = await connection.execute(
            sql.SQL(
                "SELECT member FROM {}.fdai_inventory_shared_snapshot_members(%s) member"
            ).format(sql.Identifier(schema)),
            ("pinned-source",),
        )
        assert len(await public_caller.fetchall()) == 1
        await connection.execute(
            "CREATE TEMP TABLE inventory_observation_snapshot_binding "
            "(generation_id TEXT,set_digest TEXT,bindings JSONB);"
            "SET LOCAL search_path=pg_temp"
        )
        cursor = await connection.execute(
            sql.SQL(
                "SELECT member FROM {}.fdai_inventory_shared_snapshot_members(%s) member"
            ).format(sql.Identifier(schema)),
            ("pinned-source",),
        )
        recovered = await cursor.fetchall()
        assert len(recovered) == 1
        assert recovered[0]["member"]["subject_ref"] == observations[0].subject_ref


async def save_generation(connection, observations, *, watermark: int, visible: bool = True):
    generation = observations[0].source_revision
    return await store_snapshot_membership(
        connection,
        generation_id=generation,
        source="provider",
        observation_kind="observed",
        scopes=("scope-test",),
        resource_types=("compute.vm",),
        coverage_scope="full_provider_scope",
        semantic_content_digest="sha256:" + "a" * 64,
        journal_high_watermark=watermark,
        recorded_at=observations[0].recorded_at,
        history_visible=visible,
        links_complete=True,
        records=observations,
    )


async def test_shared_generations_changed_subject_deletion_and_restart(storage_database) -> None:
    first = records("generation-0", count=3)
    unchanged = records("generation-1", at=NOW + timedelta(minutes=1), count=3)
    changed = records("generation-2", at=NOW + timedelta(minutes=2), count=2)
    changed = (
        changed[0],
        records("generation-2", at=NOW + timedelta(minutes=2), count=2, state="stopped")[1],
    )
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        initial = await append_records(connection, first)
        await save_generation(connection, first, watermark=initial.high_watermark)
        await save_generation(connection, unchanged, watermark=initial.high_watermark)
        result = await append_records(connection, (changed[1],))
        await save_generation(connection, changed, watermark=result.high_watermark)
        assert (
            await save_generation(connection, changed, watermark=result.high_watermark)
            == result.high_watermark
        )
        journal = await (
            await connection.execute("SELECT count(*) AS count FROM inventory_observation_journal")
        ).fetchone()
        assert journal["count"] == 4
        await connection.execute(
            "INSERT INTO inventory_snapshot(id,status,source,observation_kind,scopes,"
            "resource_types,metadata,started_at,completed_at) VALUES "
            "('generation-1','superseded','provider','observed','[\"scope-test\"]',"
            '\'["compute.vm"]\',\'{"coverage_scope":"full_provider_scope",'
            '"projection_complete":true}\',%s,%s)',
            (NOW, unchanged[0].recorded_at),
        )
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as restarted:
        for expected in (first, unchanged, changed):
            recovered = await load_snapshot_generation_records(
                restarted, generation_id=expected[0].source_revision, limit=10
            )
            assert recovered == expected
        history = await load_snapshot_history_records(
            restarted, resource_id="resource-0000", after=NOW - timedelta(seconds=1), limit=10
        )
        assert history == (first[0], unchanged[0], changed[0])
        previous = await load_previous_snapshot_members(
            restarted,
            source="provider",
            observation_kind="observed",
            scopes=("scope-test",),
            resource_types=("compute.vm",),
            coverage_scope="full_provider_scope",
        )
        assert previous is not None and len(previous[0]) == 3 and previous[1]
        assert (
            await load_snapshot_generation_records(restarted, generation_id="unretained", limit=10)
            is None
        )


async def test_missing_journal_baseline_and_binding_fail_closed(storage_database) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        observations = records("no-baseline", count=1)
        await save_generation(connection, observations, watermark=0)
        with pytest.raises(ValueError, match="no journal source"):
            await load_snapshot_generation_records(
                connection, generation_id="no-baseline", limit=10
            )
        await connection.execute(
            "INSERT INTO inventory_observation_snapshot_generation "
            "(generation_id,source,observation_kind,scopes,resource_types,semantic_content_digest,"
            "journal_high_watermark,recorded_at,history_visible,links_complete,storage_schema_version)"
            " VALUES ('missing-binding','provider','observed','[]','[]',%s,0,%s,TRUE,TRUE,2)",
            ("sha256:" + "a" * 64, NOW),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="binding is unavailable"):
            async with connection.transaction():
                await load_snapshot_generation_records(
                    connection, generation_id="missing-binding", limit=10
                )
        body = canonical_json(
            {"count": 1, "pages": [["00", "sha256:" + "b" * 64, "sha256:" + "b" * 64]]}
        )
        await connection.execute(
            "INSERT INTO inventory_observation_snapshot_set(digest,body) VALUES (%s,%s)",
            (content_digest(body), body),
        )
        await connection.execute(
            "INSERT INTO inventory_observation_snapshot_binding "
            "(generation_id,set_digest,bindings) VALUES ('missing-binding',%s,%s::jsonb)",
            (
                content_digest(body),
                canonical_json(
                    {
                        "generation_id": "missing-binding",
                        "observed_at": NOW.isoformat(),
                        "recorded_at": NOW.isoformat(),
                    }
                ),
            ),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="page is unavailable"):
            async with connection.transaction():
                await load_snapshot_generation_records(
                    connection, generation_id="missing-binding", limit=10
                )
        expected = records("digest-mismatch", count=1)
        wrong = records("digest-mismatch", count=1, state="stopped")
        result = await append_records(connection, wrong)
        await save_generation(connection, expected, watermark=result.high_watermark)
        with pytest.raises(ValueError, match="journal digest changed"):
            await load_snapshot_generation_records(
                connection, generation_id="digest-mismatch", limit=10
            )


@pytest.mark.parametrize("retained", [False, True])
async def test_clean_migration_round_trip_preserves_rows_and_guards(
    storage_database, retained: bool
) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        if retained:
            observations = records("retained", count=3)
            result = await append_records(connection, observations)
            await save_generation(connection, observations, watermark=result.high_watermark)
            await connection.execute(
                "INSERT INTO inventory_snapshot VALUES "
                "('retained','active','provider','observed','[]','[]','{}',%s,%s,NULL,NULL,NULL)",
                (NOW, NOW),
            )
            await stage_snapshot_batch(
                connection,
                attempt_id="retained",
                batch=InventoryBatch(
                    resources=(
                        ResourceRecord(
                            resource_id="resource",
                            type="compute.vm",
                            props={"payload": "original", "nullable": None},
                        ),
                    )
                ),
                write_batch_size=10,
            )
        expected = await (
            await connection.execute(
                "SELECT * FROM inventory_observation_snapshot_member "
                "ORDER BY generation_id,subject_kind,subject_ref"
            )
        ).fetchall()
        properties = await (
            await connection.execute(
                "SELECT * FROM inventory_snapshot_resource ORDER BY resource_id"
            )
        ).fetchall()
        await apply_migration(connection, MIGRATION, "downgrade")
        assert (
            await (
                await connection.execute(
                    "SELECT * FROM inventory_observation_snapshot_member "
                    "ORDER BY generation_id,subject_kind,subject_ref"
                )
            ).fetchall()
            == expected
        )
        assert (
            await (
                await connection.execute(
                    "SELECT * FROM inventory_snapshot_resource ORDER BY resource_id"
                )
            ).fetchall()
            == properties
        )
        await apply_migration(connection, MIGRATION)
        assert (
            await (
                await connection.execute(
                    "SELECT * FROM inventory_observation_snapshot_member "
                    "ORDER BY generation_id,subject_kind,subject_ref"
                )
            ).fetchall()
            == expected
        )
        if retained:
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                async with connection.transaction():
                    await connection.execute(
                        "DELETE FROM inventory_observation_snapshot_member_legacy"
                    )


async def test_staging_body_sharing_and_bounded_orphan_lifecycle(storage_database) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        for index in range(3):
            generation = f"stage-{index}"
            await connection.execute(
                "INSERT INTO inventory_snapshot(id,status,source,observation_kind,scopes,"
                "resource_types,started_at) VALUES (%s,'collecting','provider','observed',"
                "'[]','[]',%s)",
                (generation, NOW),
            )
            properties = {
                "payload": "shared" * 1000,
                STATE_FACT_METADATA_PROPERTY: {
                    "clock": (NOW + timedelta(minutes=index)).isoformat(),
                    "principal": f"principal-{index}",
                },
            }
            batch = InventoryBatch(
                resources=(
                    ResourceRecord(resource_id="resource", type="compute.vm", props=properties),
                    ResourceRecord(resource_id="target", type="compute.vm", props=properties),
                ),
                links=(
                    LinkRecord(
                        from_id="resource",
                        from_type="compute.vm",
                        link_type="depends_on",
                        to_id="target",
                        to_type="compute.vm",
                        link_props=properties,
                    ),
                ),
            )
            if index == 0:
                await connection.execute(
                    "INSERT INTO inventory_snapshot_resource "
                    "(snapshot_id,resource_id,resource_type,props) "
                    "VALUES (%s,'resource','compute.vm',%s::jsonb)",
                    (generation, canonical_json(properties)),
                )
            await stage_snapshot_batch(
                connection,
                attempt_id=generation,
                batch=batch,
                write_batch_size=10,
                immutable_resources=True,
            )
            row = await (
                await connection.execute(
                    "SELECT props FROM inventory_snapshot_resource WHERE snapshot_id=%s",
                    (generation,),
                )
            ).fetchone()
            assert row["props"] == properties
            link = await (
                await connection.execute(
                    "SELECT props FROM inventory_snapshot_link WHERE snapshot_id=%s", (generation,)
                )
            ).fetchone()
            assert link["props"] == properties
            with pytest.raises(ValueError, match="immutable collection chunks"):
                async with connection.transaction():
                    await stage_snapshot_batch(
                        connection,
                        attempt_id=generation,
                        batch=InventoryBatch(
                            resources=(
                                ResourceRecord(
                                    resource_id="resource",
                                    type="compute.vm",
                                    props={
                                        **properties,
                                        STATE_FACT_METADATA_PROPERTY: {"clock": "changed"},
                                    },
                                ),
                            )
                        ),
                        write_batch_size=10,
                        immutable_resources=True,
                    )
        count = await (
            await connection.execute("SELECT count(*) AS count FROM inventory_snapshot_properties")
        ).fetchone()
        assert count["count"] == 1
        await connection.execute("DELETE FROM inventory_snapshot WHERE id IN ('stage-0','stage-1')")
        assert await prune_shared_properties(connection, limit=1, max_bytes=1024 * 1024) == 0
        await connection.execute("DELETE FROM inventory_snapshot WHERE id='stage-2'")
        assert await prune_shared_properties(connection, limit=1, max_bytes=1) == 0
        assert await prune_shared_properties(connection, limit=1, max_bytes=1024 * 1024) == 1
        assert await (
            await connection.execute(
                "SELECT count(*) AS count FROM inventory_observation_snapshot_generation"
            )
        ).fetchone() == {"count": 0}


async def test_membership_actual_logical_and_physical_bytes_are_reduced(storage_database) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        for index in range(20):
            await save_generation(
                connection,
                records(f"measure-{index}", at=NOW + timedelta(minutes=index), count=512),
                watermark=0,
            )
        await connection.execute(
            "CREATE TABLE membership_baseline "
            "(LIKE inventory_observation_snapshot_member_legacy INCLUDING ALL);"
            "INSERT INTO membership_baseline SELECT * FROM inventory_observation_snapshot_member"
        )
        measured = await (
            await connection.execute(
                "SELECT (SELECT SUM(pg_column_size(b)) FROM membership_baseline b) "
                "AS legacy_logical,"
                "(SELECT SUM(octet_length(body)) FROM inventory_observation_snapshot_page) + "
                "(SELECT SUM(octet_length(body)) FROM inventory_observation_snapshot_set) + "
                "(SELECT SUM(pg_column_size(b)) FROM inventory_observation_snapshot_binding b) "
                "AS shared_logical, pg_total_relation_size('membership_baseline') "
                "AS legacy_physical,"
                "pg_total_relation_size('inventory_observation_snapshot_page') + "
                "pg_total_relation_size('inventory_observation_snapshot_set') + "
                "pg_total_relation_size('inventory_observation_snapshot_binding') "
                "AS shared_physical"
            )
        ).fetchone()
        assert measured["shared_logical"] < measured["legacy_logical"] // 2, measured
        assert measured["shared_physical"] < measured["legacy_physical"], measured
        print(f"membership PostgreSQL bytes: {measured}")


async def test_staging_actual_logical_and_physical_bytes_are_reduced(storage_database) -> None:
    async with await psycopg.AsyncConnection.connect(
        storage_database.dsn, row_factory=dict_row
    ) as connection:
        for generation_index in range(12):
            generation = f"measure-{generation_index}"
            await connection.execute(
                "INSERT INTO inventory_snapshot(id,status,source,observation_kind,scopes,"
                "resource_types,started_at) VALUES (%s,'collecting','provider','observed',"
                "'[]','[]',%s)",
                (generation, NOW),
            )
            resources = tuple(
                ResourceRecord(
                    resource_id=f"resource-{index}",
                    type="compute.vm",
                    props={
                        "payload": "".join(
                            hashlib.sha256(f"{index}:{part}".encode()).hexdigest()
                            for part in range(128)
                        ),
                        STATE_FACT_METADATA_PROPERTY: {
                            "clock": (NOW + timedelta(minutes=generation_index)).isoformat(),
                            "principal": "principal-a",
                        },
                    },
                )
                for index in range(64)
            )
            await stage_snapshot_batch(
                connection,
                attempt_id=generation,
                batch=InventoryBatch(resources=resources),
                write_batch_size=64,
            )
        await connection.execute(
            "CREATE TABLE properties_baseline AS SELECT * FROM inventory_snapshot_resource"
        )
        measured = await (
            await connection.execute(
                "SELECT (SELECT SUM(pg_column_size(props)) FROM properties_baseline) "
                "AS legacy_logical,"
                "(SELECT SUM(octet_length(body)) FROM inventory_snapshot_properties) + "
                "(SELECT SUM(pg_column_size(props_freshness)+pg_column_size(props_digest)) "
                "FROM inventory_snapshot_resource_row) AS shared_logical,"
                "pg_total_relation_size('properties_baseline') AS legacy_physical,"
                "pg_total_relation_size('inventory_snapshot_properties') + "
                "pg_total_relation_size('inventory_snapshot_resource_row') AS shared_physical"
            )
        ).fetchone()
        assert measured["shared_logical"] < measured["legacy_logical"] // 2, measured
        assert measured["shared_physical"] < measured["legacy_physical"], measured
        print(f"staging PostgreSQL bytes: {measured}")
