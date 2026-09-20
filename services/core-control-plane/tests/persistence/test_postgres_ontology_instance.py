"""Integration tests for the PostgreSQL ontology instance graph."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import psycopg
import pytest
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
    postgres_ontology,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[4]


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _type(name: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )


def _store() -> PostgresOntologyInstanceStore:
    return PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=_requires_live_db()),
        object_types=(_type("ReviewCase"), _type("ReviewCheck")),
        link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="contains_check",
                version="1.0.0",
                from_type="ReviewCase",
                to_type="ReviewCheck",
                cardinality=LinkCardinality.ONE_TO_MANY,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("query_objects", {}),
        ("scan_objects", {}),
        ("traverse", {"root_ids": ("example",)}),
        ("traverse_from_type", {"root_object_type": "ReviewCase"}),
    ],
)
async def test_graph_reads_open_one_repeatable_read_snapshot(
    monkeypatch: pytest.MonkeyPatch, operation: str, arguments: dict[str, object]
) -> None:
    store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn="postgresql://example"),
        object_types=(_type("ReviewCase"),),
        link_types=(),
    )
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []
    monkeypatch.setattr(store, "_connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        postgres_ontology, "_query_objects", AsyncMock(return_value=OntologyGraphSnapshot())
    )
    monkeypatch.setattr(
        postgres_ontology, "_traverse", AsyncMock(return_value=OntologyGraphSnapshot())
    )

    await getattr(store, operation)(**arguments)

    assert connection.execute.await_args_list[0].args == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
    )
    store._connect.assert_awaited_once()


@asynccontextmanager
async def _isolated_replacement_store() -> AsyncIterator[PostgresOntologyInstanceStore]:
    dsn = os.environ.get("FDAI_ONTOLOGY_TEST_DSN")
    if not dsn:
        pytest.skip("FDAI_ONTOLOGY_TEST_DSN requires a disposable local PostgreSQL")
    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost"}
    schema = "ontology_review_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
        await admin.execute(f"CREATE SCHEMA {schema}")
        try:
            scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
            async with await psycopg.AsyncConnection.connect(scoped) as connection:
                await connection.execute(
                    "CREATE TABLE ontology_resource (id TEXT PRIMARY KEY, "
                    "object_type TEXT NOT NULL, properties JSONB NOT NULL, "
                    "revision BIGINT NOT NULL, type_version TEXT NOT NULL, "
                    "catalog_digest TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW());"
                    "CREATE TABLE ontology_link_type (name TEXT PRIMARY KEY);"
                    "INSERT INTO ontology_link_type VALUES ('contains_check');"
                    "CREATE TABLE ontology_link (link_type TEXT NOT NULL, "
                    "from_id TEXT REFERENCES ontology_resource(id), "
                    "to_id TEXT REFERENCES ontology_resource(id), properties JSONB NOT NULL, "
                    "type_version TEXT NOT NULL, catalog_digest TEXT NOT NULL, "
                    "PRIMARY KEY(from_id, link_type, to_id));"
                    "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                    "updated_at TIMESTAMPTZ DEFAULT NOW())"
                )
            yield PostgresOntologyInstanceStore(
                config=PostgresOntologyInstanceStoreConfig(dsn=scoped),
                object_types=(_type("ReviewCase"), _type("ReviewCheck")),
                link_types=(
                    OntologyLinkType(
                        schema_version="1.0.0",
                        name="contains_check",
                        version="1.0.0",
                        from_type="ReviewCase",
                        to_type="ReviewCheck",
                        cardinality=LinkCardinality.ONE_TO_MANY,
                    ),
                ),
            )
        finally:
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")


def _review_object(identifier: str, object_type: str = "ReviewCase") -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=identifier, object_type=object_type, properties={"id": identifier, "status": "open"}
    )


@pytest.mark.parametrize("defect", ["none", "manifest", "chunk", "missing", "mutation"])
def test_prepared_ontology_inputs_are_content_bound_and_frozen(defect) -> None:
    from fdai.delivery.persistence.postgres_ontology_prepared import (
        prepare_replacement,
        restore_replacement,
    )
    from fdai.shared.providers.ontology_instance import pin_object_record

    store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn="postgresql://example"),
        object_types=(_type("ReviewCase"),),
        link_types=(),
    )
    properties = {"id": "case", "status": "open"}
    record = pin_object_record(
        OntologyObjectRecord(
            id="case",
            object_type="ReviewCase",
            properties=properties,
        ),
        store._release,
    )
    prepared = prepare_replacement(
        objects=(record,),
        links=(),
        previous_object_ids=(),
        previous_link_keys=(),
        release_digest=store._release.digest,
        expected_active_generation="example-generation",
        state_updates={"example-status": {"ready": True}},
        observation_projection_watermark=None,
    )
    expected_digest = prepared.digest
    if defect == "manifest":
        prepared = replace(
            prepared, manifest=prepared.manifest.replace('"ready":true', '"ready":1')
        )
    elif defect == "chunk":
        prepared = replace(prepared, chunks=(prepared.chunks[0].replace('"open"', '"closed"'),))
    elif defect == "missing":
        prepared = replace(prepared, chunks=())
    elif defect == "mutation":
        properties["status"] = "closed"
    if defect in {"manifest", "chunk", "missing"}:
        with pytest.raises(OntologyInstanceValidationError, match="prepared ontology"):
            restore_replacement(prepared, expected_digest=expected_digest)
    else:
        manifest, objects, links = restore_replacement(prepared, expected_digest=expected_digest)
        assert objects[0].properties == {"id": "case", "status": "open"}
        assert links == ()
        assert manifest["expected_active_generation"] == "example-generation"


async def test_isolated_replacement_replay_is_noop_and_foreign_deletion_is_blocked() -> None:
    async with _isolated_replacement_store() as store:
        objects = (_review_object("case"), _review_object("check", "ReviewCheck"))
        link = OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check")
        await store.replace_subgraph(objects=objects, links=(link,))
        first = await store.query_objects()
        await store.replace_subgraph(
            objects=first.objects,
            links=first.links,
            previous_object_ids=("case", "check"),
            previous_link_keys=(("case", "contains_check", "check"),),
        )
        assert await store.query_objects() == first
        with pytest.raises(OntologyInstanceValidationError, match="foreign relationships"):
            await store.replace_subgraph(objects=(), links=(), previous_object_ids=("case",))
        assert await store.query_objects() == first
        await store.replace_subgraph(
            objects=(),
            links=(),
            previous_object_ids=("case", "check"),
            previous_link_keys=(("case", "contains_check", "check"),),
        )
        assert (await store.query_objects()).objects == ()


async def test_isolated_snapshot_pages_pin_committed_version_across_new_publication():
    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'snapshot-one')"
            )
        assert await store.pin_inventory_snapshot() is None
        originals = (_review_object("case"), _review_object("check", "ReviewCheck"))
        link = OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check")
        await store.replace_subgraph_with_state(
            objects=originals,
            links=(link,),
            previous_object_ids=(),
            previous_link_keys=(),
            state_updates={},
            expected_active_generation="snapshot-one",
        )
        pin = await store.pin_inventory_snapshot()
        first = await store.read_inventory_snapshot_page(snapshot_digest=pin, limit=1)
        assert first.objects[0].id == "case" and first.objects[0].revision == 1
        assert first.next_cursor is not None
        async with await store._connect() as connection:
            await connection.execute("UPDATE inventory_active SET snapshot_id='snapshot-two'")
        with pytest.raises(OntologyInstanceValidationError, match="unavailable or pending"):
            await store.pin_inventory_snapshot()
        current = await store.query_objects()
        changed = tuple(
            replace(record, properties={**record.properties, "status": "closed"})
            for record in current.objects
        )
        await store.replace_subgraph_with_state(
            objects=changed,
            links=(),
            previous_object_ids=("case", "check"),
            previous_link_keys=(("case", "contains_check", "check"),),
            state_updates={},
            expected_active_generation="snapshot-two",
        )
        next_page = await store.read_inventory_snapshot_page(
            snapshot_digest=pin, cursor=first.next_cursor, limit=1
        )
        assert next_page.generation == first.generation == "snapshot-one"
        assert next_page.objects[0].properties["status"] == "open"
        assert next_page.objects[0].revision == 1 and next_page.next_cursor is None
        edges = await store.read_inventory_snapshot_page(snapshot_digest=pin, relationships=True)
        assert edges.links[0].to_id == "check"
        new_pin = await store.pin_inventory_snapshot()
        assert new_pin != pin
        new_page = await store.read_inventory_snapshot_page(snapshot_digest=new_pin)
        assert all(
            item.revision == 2 and item.properties["status"] == "closed"
            for item in new_page.objects
        )
        with pytest.raises(ValueError, match="version and kind"):
            await store.read_inventory_snapshot_page(
                snapshot_digest=new_pin, cursor=first.next_cursor
            )


@pytest.mark.parametrize(
    "defect",
    [
        "receipt_missing",
        "receipt_corrupt",
        "manifest_missing",
        "manifest_corrupt",
        "chunk_missing",
        "chunk_corrupt",
        "database_rebuilt",
        "cursor_kind",
        "cursor_version",
        "cursor_past_end",
        "limit_bool",
        "limit_oversize",
        "reader_role",
        "legacy_pointer",
    ],
)
async def test_isolated_snapshot_read_fails_closed_without_current_graph_fallback(defect):
    from fdai.delivery.persistence.postgres_ontology_snapshot import read_snapshot_page
    from psycopg import sql

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'snapshot-example')"
            )
        await store.replace_subgraph_with_state(
            objects=(_review_object("case"),),
            links=(),
            previous_object_ids=(),
            previous_link_keys=(),
            state_updates={},
            expected_active_generation="snapshot-example",
        )
        pin = await store.pin_inventory_snapshot()
        request = dict(snapshot_digest=pin)
        role_name = None
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key=%s", ("ontology-committed:" + pin,)
            )
            receipt = (await cursor.fetchone())["value"]
            if defect == "database_rebuilt":
                await connection.execute("DELETE FROM state_kv")
            elif defect.startswith(("receipt_", "manifest_", "chunk_")):
                target = {
                    "receipt": "ontology-committed:" + pin,
                    "manifest": "ontology-prepared:" + receipt["prepared_digest"],
                    "chunk": "ontology-prepared:" + receipt["partitions"][0]["digest"],
                }[defect.split("_")[0]]
                query = (
                    "DELETE FROM state_kv WHERE key=%s"
                    if defect.endswith("missing")
                    else "UPDATE state_kv SET value='{}' WHERE key=%s"
                )
                await connection.execute(query, (target,))
            elif defect == "legacy_pointer":
                await connection.execute(
                    "UPDATE state_kv SET value=value-'snapshot_digest' "
                    "WHERE key='inventory-ontology:prepared-snapshot'"
                )
            elif defect == "reader_role":
                role_name = "snapshot_reader_" + uuid.uuid4().hex
                cursor = await connection.execute("SELECT current_schema() AS name")
                schema = (await cursor.fetchone())["name"]
                await connection.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER").format(sql.Identifier(role_name))
                )
                await connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(role_name)
                    )
                )
                await connection.execute(
                    sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(role_name)
                    )
                )
        if defect == "cursor_kind":
            request["cursor"] = pin + ":links:0"
        elif defect == "cursor_version":
            request["cursor"] = "sha256:" + "f" * 64 + ":objects:0"
        elif defect == "cursor_past_end":
            request["cursor"] = pin + ":objects:2"
        elif defect.startswith("limit_"):
            request["limit"] = True if defect == "limit_bool" else 1001
        if role_name is not None:
            options = (
                conninfo_to_dict(store._config.dsn).get("options", "") + f" -c role={role_name}"
            )
            config = replace(store._config, dsn=make_conninfo(store._config.dsn, options=options))
            try:
                page = await read_snapshot_page(config, **request)
                assert [item.id for item in page.objects] == ["case"]
                assert page.objects[0].revision == 1
            finally:
                async with await store._connect() as connection:
                    await connection.execute(
                        sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
                    )
                    await connection.execute(
                        sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name))
                    )
        elif defect == "legacy_pointer":
            with pytest.raises(OntologyInstanceValidationError, match="unavailable or pending"):
                await store.pin_inventory_snapshot()
        else:
            with pytest.raises(ValueError):
                await store.read_inventory_snapshot_page(**request)
        assert await store.get_object("case") is not None


async def test_isolated_snapshot_read_fetches_only_selected_partition(monkeypatch):
    from fdai.delivery.persistence import postgres_ontology_snapshot as snapshots

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'snapshot-example')"
            )
        objects = tuple(_review_object(f"case-{index:04d}") for index in range(1001))
        await store.replace_subgraph_with_state(
            objects=objects,
            links=(),
            previous_object_ids=(),
            previous_link_keys=(),
            state_updates={},
            expected_active_generation="snapshot-example",
        )
        pin = await store.pin_inventory_snapshot()
        calls = []
        read_content = snapshots._read_content

        async def observe(connection, prefix, digest, limit):
            calls.append((prefix, digest))
            return await read_content(connection, prefix, digest, limit)

        monkeypatch.setattr(snapshots, "_read_content", observe)
        page = await store.read_inventory_snapshot_page(
            snapshot_digest=pin, cursor=pin + ":objects:1000", limit=1
        )
        assert page.objects[0].id == "case-1000"
        assert page.next_cursor is None
        assert len(calls) == 3
        empty = await store.read_inventory_snapshot_page(snapshot_digest=pin, relationships=True)
        assert empty.total_count == 0 and empty.links == () and empty.next_cursor is None


async def test_isolated_snapshot_read_remains_consistent_during_concurrent_receipt_removal(
    monkeypatch,
):
    from fdai.delivery.persistence import postgres_ontology_snapshot as snapshots

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'snapshot-example')"
            )
        await store.replace_subgraph_with_state(
            objects=(_review_object("case"),),
            links=(),
            previous_object_ids=(),
            previous_link_keys=(),
            state_updates={},
            expected_active_generation="snapshot-example",
        )
        pin = await store.pin_inventory_snapshot()
        read_content = snapshots._read_content
        deleted = False

        async def remove_after_receipt(connection, prefix, digest, limit):
            nonlocal deleted
            content = await read_content(connection, prefix, digest, limit)
            if not deleted:
                deleted = True
                async with await store._connect() as writer:
                    await writer.execute("DELETE FROM state_kv")
            return content

        monkeypatch.setattr(snapshots, "_read_content", remove_after_receipt)
        page = await store.read_inventory_snapshot_page(snapshot_digest=pin)
        assert page.objects[0].id == "case"
        with pytest.raises(OntologyInstanceValidationError, match="unavailable"):
            await store.read_inventory_snapshot_page(snapshot_digest=pin)


async def test_isolated_published_snapshot_receipt_binds_actual_revisions():
    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'snapshot-example')"
            )
        record = _review_object("case")
        for expected_revision, status in ((1, "open"), (1, "open"), (2, "closed")):
            await store.replace_subgraph_with_state(
                objects=(replace(record, properties={"id": "case", "status": status}),),
                links=(),
                previous_object_ids=("case",) if record.revision else (),
                previous_link_keys=(),
                state_updates={},
                expected_active_generation="snapshot-example",
            )
            record = await store.get_object("case")
            assert record.revision == expected_revision
            async with await store._connect() as connection:
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key='inventory-ontology:prepared-snapshot'"
                )
                pointer = (await cursor.fetchone())["value"]
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key=%s",
                    ("ontology-committed:" + pointer["snapshot_digest"],),
                )
                receipt = (await cursor.fetchone())["value"]
            assert receipt["object_revisions"] == {"case": expected_revision}
            assert receipt["prepared_digest"] == pointer["digest"]
            assert receipt["generation"] == "snapshot-example"


@pytest.mark.parametrize(
    "defect",
    [
        "release",
        "duplicate",
        "watermark_bool",
        "watermark_negative",
        "generation",
        "generation_size",
        "graph_bytes",
        "manifest_bytes",
        "chunk_bytes",
        "objects",
        "owners",
    ],
)
def test_prepared_ontology_admission_bounds(monkeypatch, defect):
    from fdai.delivery.persistence import postgres_ontology_prepared as prepared_module
    from fdai.shared.providers.ontology_instance import pin_object_record

    store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn="postgresql://example"),
        object_types=(_type("ReviewCase"),),
        link_types=(),
    )
    record = pin_object_record(_review_object("case"), store._release)
    arguments = dict(
        objects=(record,),
        links=(),
        previous_object_ids=(),
        previous_link_keys=(),
        release_digest=store._release.digest,
        expected_active_generation="example-generation",
        state_updates={},
        observation_projection_watermark=None,
    )
    if defect == "release":
        arguments["release_digest"] = "sha256:" + "f" * 64
    elif defect == "duplicate":
        arguments["objects"] = (record, record)
    elif defect.startswith("watermark"):
        arguments["observation_projection_watermark"] = True if defect == "watermark_bool" else -1
    elif defect.startswith("generation"):
        arguments["expected_active_generation"] = " " if defect == "generation" else "x" * 257
    elif defect in {"graph_bytes", "manifest_bytes", "chunk_bytes"}:
        monkeypatch.setattr(prepared_module, "_MAX_" + defect.upper(), 100)
    elif defect == "objects":
        arguments["objects"] = (record,) * 50_001
    elif defect == "owners":
        arguments["previous_object_ids"] = ("case",) * 50_001
    with pytest.raises(OntologyInstanceValidationError, match="prepared ontology"):
        prepared_module.prepare_replacement(**arguments)


def test_prepared_ontology_chunks_preserve_canonical_order_and_record_limits():
    import json

    from fdai.delivery.persistence.postgres_ontology_prepared import (
        prepare_replacement,
        restore_replacement,
    )
    from fdai.shared.providers.ontology_instance import pin_object_record

    store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn="postgresql://example"),
        object_types=(_type("ReviewCase"),),
        link_types=(),
    )
    objects = tuple(
        pin_object_record(_review_object(f"case-{index:04d}"), store._release)
        for index in range(1200)
    )
    arguments = dict(
        links=(),
        previous_object_ids=(),
        previous_link_keys=(),
        release_digest=store._release.digest,
        expected_active_generation="example-generation",
        state_updates={},
        observation_projection_watermark=None,
    )
    prepared = prepare_replacement(objects=objects, **arguments)
    assert prepare_replacement(objects=tuple(reversed(objects)), **arguments) == prepared
    assert len(prepared.chunks) == 2
    assert all(len(json.loads(chunk)["records"]) <= 1000 for chunk in prepared.chunks)
    assert all(len(chunk.encode()) <= 1024 * 1024 for chunk in prepared.chunks)
    assert restore_replacement(prepared, expected_digest=prepared.digest)[1] == objects


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "manifest",
        "chunk",
        "missing",
        "active_generation",
        "conflict",
        "missing_endpoint",
        "state_write",
        "lost_revision",
        "caller_mutation",
        "cancel",
        "wrong_release",
    ],
)
async def test_isolated_prepared_ontology_publication_rechecks_durable_inputs(monkeypatch, defect):
    from fdai.delivery.persistence.postgres_ontology_prepared import persist_replacement

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE, 'example-generation')"
            )
        retained = []
        state_updates = {"example-status": {"ready": True}}
        before = await store.query_objects()

        async def persist(config, prepared):
            nonlocal before
            await persist_replacement(config, prepared)
            await persist_replacement(config, prepared)
            retained.append(prepared)
            assert (await store.query_objects()).objects == ()
            async with await store._connect() as connection:
                if defect == "manifest":
                    await connection.execute(
                        "UPDATE state_kv SET value='{}' WHERE key=%s",
                        ("ontology-prepared:" + prepared.digest,),
                    )
                elif defect in {"chunk", "missing"}:
                    import json

                    key = "ontology-prepared:" + json.loads(prepared.manifest)["chunks"][0]
                    if defect == "chunk":
                        await connection.execute(
                            "UPDATE state_kv SET value='{}' WHERE key=%s", (key,)
                        )
                    else:
                        await connection.execute("DELETE FROM state_kv WHERE key=%s", (key,))
                elif defect == "active_generation":
                    await connection.execute(
                        "UPDATE inventory_active SET snapshot_id='other-generation'"
                    )
                elif defect == "state_write":
                    await connection.execute(
                        "CREATE FUNCTION reject_prepared_commit() RETURNS trigger LANGUAGE plpgsql "
                        "AS $$ BEGIN RAISE EXCEPTION 'synthetic commit failure'; END $$;"
                        "CREATE TRIGGER reject_prepared_commit BEFORE INSERT ON state_kv "
                        "FOR EACH ROW WHEN (NEW.key='inventory-ontology:prepared-snapshot') "
                        "EXECUTE FUNCTION reject_prepared_commit()"
                    )
                elif defect == "conflict":
                    await connection.execute(
                        "UPDATE state_kv SET value='{}' WHERE key=%s",
                        ("ontology-prepared:" + prepared.digest,),
                    )
            if defect == "conflict":
                await persist_replacement(config, prepared)
            elif defect == "lost_revision":
                await store.replace_subgraph(objects=(_review_object("case"),), links=())
                before = await store.query_objects()
            elif defect == "caller_mutation":
                state_updates["example-status"]["ready"] = False
            elif defect == "cancel":
                raise asyncio.CancelledError()

        monkeypatch.setattr(postgres_ontology, "persist_replacement", persist)

        async def publish():
            record = _review_object("case")
            if defect == "wrong_release":
                from fdai.shared.providers.ontology_instance import pin_object_record

                record = pin_object_record(record, store._release)
                record = replace(
                    record,
                    type_ref=record.type_ref.model_copy(
                        update={"catalog_digest": "sha256:" + "f" * 64},
                    ),
                )
            await store.replace_subgraph_with_state(
                objects=(record,),
                links=(
                    OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="missing"),
                )
                if defect == "missing_endpoint"
                else (),
                previous_object_ids=(),
                previous_link_keys=(),
                state_updates=state_updates,
                expected_active_generation="example-generation",
            )

        if defect in {"none", "caller_mutation"}:
            await publish()
            assert [item.id for item in (await store.query_objects()).objects] == ["case"]
        else:
            error_type = (
                asyncio.CancelledError
                if defect == "cancel"
                else psycopg.errors.RaiseException
                if defect == "state_write"
                else OntologyInstanceValidationError
            )
            with pytest.raises(error_type):
                await publish()
            assert await store.query_objects() == before
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key=%s", ("inventory-ontology:prepared-snapshot",)
            )
            row = await cursor.fetchone()
            if defect in {"none", "caller_mutation"}:
                assert row["value"]["digest"] == retained[0].digest
            else:
                assert row is None
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key='example-status'"
            )
            status = await cursor.fetchone()
            assert (status["value"] if status else None) == (
                {"ready": True} if defect in {"none", "caller_mutation"} else None
            )
            cursor = await connection.execute(
                "SELECT COUNT(*) AS count FROM state_kv "
                "WHERE starts_with(key,'ontology-committed:')"
            )
            assert (await cursor.fetchone())["count"] == (
                1 if defect in {"none", "caller_mutation"} else 0
            )


@pytest.mark.parametrize(
    "scenario",
    [
        "external_changed",
        "removed_changed",
        "absent_created",
        "absent_after_check",
        "unchanged",
    ],
)
async def test_isolated_prepared_dependencies_reject_drift_and_preserve_new_foreign_rows(
    monkeypatch,
    scenario,
):
    from fdai.delivery.persistence.postgres_ontology_prepared import (
        persist_replacement,
        verify_replacement_dependencies,
    )

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE, 'example-generation')"
            )
        if scenario == "external_changed":
            await store.upsert_object(_review_object("dependency", "ReviewCheck"))
        elif scenario in {"removed_changed", "unchanged"}:
            await store.upsert_object(_review_object("dependency"))
        before = await store.query_objects()

        async def persist(config, prepared):
            nonlocal before
            await persist_replacement(config, prepared)
            if scenario in {"external_changed", "removed_changed"}:
                original = await store.get_object("dependency")
                await store.upsert_object(
                    replace(
                        original,
                        properties={
                            **original.properties,
                            "status": "changed",
                        },
                    ),
                    expected_revision=original.revision,
                )
            elif scenario == "absent_created":
                await store.create_object_if_absent(_review_object("dependency"))
            before = await store.query_objects()

        async def verify(connection, manifest):
            await verify_replacement_dependencies(connection, manifest)
            if scenario == "absent_after_check":
                await store.create_object_if_absent(_review_object("dependency"))

        monkeypatch.setattr(postgres_ontology, "persist_replacement", persist)
        monkeypatch.setattr(postgres_ontology, "verify_replacement_dependencies", verify)

        async def publish():
            await store.replace_subgraph_with_state(
                objects=(_review_object("new-case"),),
                links=(
                    OntologyLinkRecord(
                        link_type="contains_check", from_id="new-case", to_id="dependency"
                    ),
                )
                if scenario == "external_changed"
                else (),
                previous_object_ids=() if scenario == "external_changed" else ("dependency",),
                previous_link_keys=(),
                state_updates={},
                expected_active_generation="example-generation",
            )

        if scenario in {"unchanged", "absent_after_check"}:
            await publish()
            identifiers = {record.id for record in (await store.query_objects()).objects}
            assert identifiers == (
                {"new-case", "dependency"} if scenario == "absent_after_check" else {"new-case"}
            )
        else:
            with pytest.raises(
                OntologyInstanceValidationError, match="dependency revision changed"
            ):
                await publish()
            assert await store.query_objects() == before


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "generation",
        "manifest",
        "damage",
        "status",
        "graph",
        "release",
        "future",
        "missing_object",
        "rollback",
        "process_restart",
        "concurrent",
        "runtime_role",
        "reader_role",
    ],
)
async def test_isolated_cursor_repair_requires_exact_committed_graph(defect):
    import getpass
    import json
    from datetime import UTC, datetime, timedelta

    from fdai.delivery.persistence.postgres_inventory_cursor_repair import (
        damage_digest,
        inspect_inventory_cursor,
        repair_inventory_cursor,
    )
    from fdai.runtime.inventory_ontology_manifest import _bounded_digest
    from psycopg.types.json import Jsonb

    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
        original_time = datetime.now(UTC) - timedelta(hours=1)
        manifest = {
            "schema_version": "1.3.0",
            "generation": "example-generation",
            "ontology_release_digest": store._release.digest,
            "complete": True,
            "relationship_complete": True,
            "dropped_reasons": [],
            "object_ids": ["case"],
            "link_keys": [],
            "object_content": [
                {
                    "id": "case",
                    "object_type": "ReviewCase",
                    "properties": {"id": "case", "status": "open"},
                }
            ],
            "link_content": [],
        }
        manifest["manifest_digest"] = _bounded_digest(manifest)
        status = {
            "generation": "example-generation",
            "manifest_digest": manifest["manifest_digest"],
            "status": "available",
            "complete": True,
        }
        marker = {"sequence": "broken"}
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "CREATE TABLE inventory_snapshot (id TEXT PRIMARY KEY,completed_at TIMESTAMPTZ);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await connection.execute(
                "INSERT INTO inventory_snapshot VALUES ('example-generation',%s)",
                (datetime.now(UTC) + timedelta(hours=1) if defect == "future" else original_time,),
            )
            if defect == "manifest":
                manifest["complete"] = False
            elif defect == "status":
                status["status"] = "unavailable"
            elif defect == "graph":
                await connection.execute("UPDATE ontology_resource SET properties='{}'")
            elif defect == "release":
                await connection.execute("UPDATE ontology_resource SET catalog_digest='other'")
            elif defect == "missing_object":
                await connection.execute("DELETE FROM ontology_resource")
            for name, value in (
                ("manifest", manifest),
                ("status", status),
                ("invalidation", marker),
            ):
                await connection.execute(
                    "INSERT INTO state_kv (key,value) VALUES (%s,%s)",
                    ("inventory-ontology:" + name, Jsonb(value)),
                )
            if defect == "rollback":
                await connection.execute(
                    "CREATE FUNCTION reject_cursor() RETURNS trigger LANGUAGE plpgsql "
                    "AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$;"
                    "CREATE TRIGGER reject_cursor BEFORE INSERT ON state_kv "
                    "FOR EACH ROW WHEN (NEW.key='inventory-ontology:cursor-floor') "
                    "EXECUTE FUNCTION reject_cursor()"
                )

        async def graph_rows():
            async with await store._connect() as connection:
                cursor = await connection.execute("SELECT * FROM ontology_resource ORDER BY id")
                return await cursor.fetchall()

        before = await graph_rows()
        request = dict(
            actor=getpass.getuser() if defect == "process_restart" else "example-maintainer",
            repair_id="repair-example",
            expected_generation="changed" if defect == "generation" else "example-generation",
            expected_manifest_digest=manifest["manifest_digest"],
            expected_damage_digest=damage_digest(marker, None)
            if defect != "damage"
            else "sha256:" + "f" * 64,
        )
        role_name = None
        if defect in {"runtime_role", "reader_role"}:
            from psycopg import sql

            role_name = "cursor_repair_" + uuid.uuid4().hex
            async with await store._connect() as connection:
                cursor = await connection.execute("SELECT current_schema() AS name")
                schema_name = (await cursor.fetchone())["name"]
                await connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT NOBYPASSRLS"
                    ).format(sql.Identifier(role_name))
                )
                await connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema_name), sql.Identifier(role_name)
                    )
                )
                grants = (
                    sql.SQL("SELECT")
                    if defect == "reader_role"
                    else sql.SQL("SELECT,INSERT,UPDATE,DELETE")
                )
                await connection.execute(
                    sql.SQL("GRANT {} ON ALL TABLES IN SCHEMA {} TO {}").format(
                        grants, sql.Identifier(schema_name), sql.Identifier(role_name)
                    )
                )
            role_options = (
                conninfo_to_dict(store._config.dsn).get("options", "") + f" -c role={role_name}"
            )
            repair_config = replace(
                store._config, dsn=make_conninfo(store._config.dsn, options=role_options)
            )
        else:
            repair_config = store._config
        if defect in {"none", "process_restart", "concurrent", "runtime_role"}:
            basis = await inspect_inventory_cursor(store._config)
            assert basis == {
                "status": "inspected",
                **{key: value for key, value in request.items() if key.startswith("expected_")},
            }
            receipt = await repair_inventory_cursor(repair_config, **request)
            if role_name is not None:
                assert receipt["database_actor"] == role_name
            if defect == "process_restart":
                command = [
                    sys.executable,
                    "-m",
                    "fdai.delivery.persistence.postgres_inventory_cursor_repair",
                    "--apply",
                ]
                for name, value in request.items():
                    if name != "actor":
                        command.extend(("--" + name.replace("_", "-"), value))
                process = await asyncio.create_subprocess_exec(
                    *command,
                    env={**os.environ, "FDAI_STATE_STORE_DSN": store._config.dsn},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                assert process.returncode == 0, stderr.decode()
                assert json.loads(stdout) == {
                    "status": "repaired",
                    "receipt_digest": receipt["content_digest"],
                    "epoch": receipt["epoch"],
                }
            elif defect == "concurrent":
                simultaneous = await asyncio.gather(
                    *(repair_inventory_cursor(store._config, **request) for _ in range(2))
                )
                assert simultaneous == [receipt, receipt]
            assert await repair_inventory_cursor(store._config, **request) == receipt
            assert receipt["observed_at"] == original_time.isoformat()
            with pytest.raises(ValueError, match="receipt conflicts"):
                await repair_inventory_cursor(
                    store._config, **{**request, "actor": "other-maintainer"}
                )
        else:
            with pytest.raises(
                psycopg.errors.RaiseException
                if defect == "rollback"
                else psycopg.errors.InsufficientPrivilege
                if defect == "reader_role"
                else ValueError
            ):
                await repair_inventory_cursor(repair_config, **request)
        assert await graph_rows() == before
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT key,value FROM state_kv ORDER BY key")
            states = {row["key"]: row["value"] for row in await cursor.fetchall()}
            assert states["inventory-ontology:manifest"] == manifest
            assert states["inventory-ontology:status"] == status
            if defect in {"none", "process_restart", "concurrent", "runtime_role"}:
                assert states["inventory-ontology:invalidation"]["epoch"] == receipt["epoch"]
                assert states["inventory-ontology:cursor-floor"] == {
                    "epoch": receipt["epoch"],
                    "sequence": 1,
                }
            else:
                assert states["inventory-ontology:invalidation"] == marker
                assert "inventory-ontology:cursor-floor" not in states
                assert not any(
                    key.startswith("inventory-ontology:cursor-repair:") for key in states
                )
        if role_name is not None:
            async with await store._connect() as connection:
                await connection.execute(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
                )
                await connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest.mark.parametrize("defect", ["none", "numeric_type", "locked_mutation"])
async def test_isolated_prepared_content_verification_is_exact_and_locked(monkeypatch, defect):
    from fdai.delivery.persistence.postgres_ontology_prepared import (
        persist_replacement,
        restore_replacement,
        verify_replacement_content,
    )

    order = []

    class ObservedConnection(psycopg.AsyncConnection):
        async def execute(self, query, params=None, **kwargs):
            result = await super().execute(query, params, **kwargs)
            if query == "SELECT pg_advisory_xact_lock(%s)" and params == (
                postgres_ontology._SUBGRAPH_REPLACEMENT_LOCK,
            ):
                order.append("writer_lock")
            return result

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )

        async def connect():
            return await ObservedConnection.connect(store._config.dsn, row_factory=dict_row)

        def restore(prepared, **kwargs):
            order.append("restore")
            return restore_replacement(prepared, **kwargs)

        async def persist(config, prepared):
            await persist_replacement(config, prepared)
            if defect == "numeric_type":
                async with await store._connect() as connection:
                    await connection.execute(
                        "UPDATE state_kv SET "
                        "value=jsonb_set(value,'{state_updates,projection,count}','1.0') "
                        "WHERE key=%s",
                        ("ontology-prepared:" + prepared.digest,),
                    )

        async def verify(connection, prepared):
            order.append("verify")
            await verify_replacement_content(connection, prepared)
            if defect == "locked_mutation":
                with pytest.raises(psycopg.errors.QueryCanceled):
                    async with await store._connect() as competing:
                        await competing.execute("SELECT set_config('statement_timeout','100',true)")
                        await competing.execute(
                            "DELETE FROM state_kv WHERE key=%s",
                            ("ontology-prepared:" + prepared.digest,),
                        )

        monkeypatch.setattr(store, "_connect", connect)
        monkeypatch.setattr(postgres_ontology, "restore_replacement", restore)
        monkeypatch.setattr(postgres_ontology, "persist_replacement", persist)
        monkeypatch.setattr(postgres_ontology, "verify_replacement_content", verify)

        async def publish():
            await store.replace_subgraph_with_state(
                objects=(_review_object("case"),),
                links=(),
                previous_object_ids=(),
                previous_link_keys=(),
                state_updates={"projection": {"count": 1}},
                expected_active_generation="example-generation",
            )

        if defect == "numeric_type":
            with pytest.raises(OntologyInstanceValidationError, match="durable content changed"):
                await publish()
            assert await store.get_object("case") is None
        else:
            await publish()
            assert await store.get_object("case") is not None
        assert order == ["restore", "writer_lock", "verify"]


@pytest.mark.parametrize("publication", ["direct", "prepared"])
async def test_isolated_ontology_capacity_measurement(monkeypatch, publication):
    import hashlib
    import json
    import resource
    import time

    count = int(os.environ.get("FDAI_ONTOLOGY_CAPACITY_ROWS", "1000"))
    padding = int(os.environ.get("FDAI_ONTOLOGY_CAPACITY_PADDING", "64"))
    assert 2 <= count <= 50_000 and 0 <= padding <= 512
    occupancy = []

    class TimedConnection(psycopg.AsyncConnection):
        lock_started = None

        async def execute(self, query, params=None, **kwargs):
            result = await super().execute(query, params, **kwargs)
            if query == "SELECT pg_advisory_xact_lock(%s)" and params == (
                postgres_ontology._SUBGRAPH_REPLACEMENT_LOCK,
            ):
                self.lock_started = time.perf_counter()
            return result

        @asynccontextmanager
        async def transaction(self, *args, **kwargs):
            try:
                async with super().transaction(*args, **kwargs) as transaction:
                    yield transaction
            finally:
                if self.lock_started is not None:
                    occupancy.append(time.perf_counter() - self.lock_started)
                    self.lock_started = None

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'capacity-generation')"
            )

        async def connect():
            return await TimedConnection.connect(store._config.dsn, row_factory=dict_row)

        monkeypatch.setattr(store, "_connect", connect)
        objects = tuple(
            OntologyObjectRecord(
                id=f"capacity-{index:06d}",
                object_type="ReviewCase" if index == 0 else "ReviewCheck",
                properties={"id": f"capacity-{index:06d}", "status": "x" * padding},
            )
            for index in range(count)
        )
        links = tuple(
            OntologyLinkRecord(link_type="contains_check", from_id=objects[0].id, to_id=item.id)
            for item in objects[1:]
        )
        durations = []
        for replay in (False, True):
            started = time.perf_counter()
            await store.replace_subgraph(
                objects=tuple(replace(item, revision=1) for item in objects) if replay else objects,
                links=links,
                previous_object_ids=tuple(item.id for item in objects) if replay else (),
                previous_link_keys=tuple(
                    (item.from_id, item.link_type, item.to_id) for item in links
                )
                if replay
                else (),
                _expected_active_generation="capacity-generation"
                if publication == "prepared"
                else None,
                _state_updates={"capacity-status": {"complete": True, "count": count}},
            )
            durations.append(time.perf_counter() - started)
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) AS count,MAX(revision) AS revision FROM ontology_resource"
            )
            assert await cursor.fetchone() == {"count": count, "revision": 1}
            cursor = await connection.execute("SELECT COUNT(*) AS count FROM ontology_link")
            assert (await cursor.fetchone())["count"] == count - 1
        assert len(occupancy) == 2 and all(0 < value < 60 for value in occupancy)
        restart = None
        if publication == "prepared":
            code = """
import asyncio, json, os, resource, runpy, sys, time
from fdai.delivery.persistence.postgres_ontology_prepared import load_replacement
fixture = runpy.run_path(os.environ['CAPACITY_TEST_PATH'])
async def main():
    store = fixture['PostgresOntologyInstanceStore'](
        config=fixture['PostgresOntologyInstanceStoreConfig'](dsn=os.environ['CAPACITY_TEST_DSN']),
        object_types=(fixture['_type']('ReviewCase'),fixture['_type']('ReviewCheck')),
        link_types=(fixture['OntologyLinkType'](schema_version='1.0.0',name='contains_check',
            version='1.0.0',from_type='ReviewCase',to_type='ReviewCheck',
            cardinality=fixture['LinkCardinality'].ONE_TO_MANY),),
    )
    started = time.perf_counter()
    async with await store._connect() as connection:
        cursor = await connection.execute(
            "SELECT value FROM state_kv WHERE key='inventory-ontology:prepared-snapshot'")
        pointer = (await cursor.fetchone())['value']
        manifest, objects, links = await load_replacement(
            connection, expected_digest=pointer['digest'])
    await store.replace_subgraph_with_state(objects=objects,links=links,
        previous_object_ids=tuple(manifest['previous_object_ids']),
        previous_link_keys=tuple(tuple(key) for key in manifest['previous_link_keys']),
        expected_active_generation=manifest['expected_active_generation'],
        state_updates=manifest['state_updates'])
    print(json.dumps({'seconds':time.perf_counter()-started,
        'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
            (1 if sys.platform == 'darwin' else 1024)}))
asyncio.run(main())
"""
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                env={
                    **os.environ,
                    "CAPACITY_TEST_PATH": __file__,
                    "CAPACITY_TEST_DSN": store._config.dsn,
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, stderr.decode()
            restart = json.loads(stdout)
            assert 0 < restart["seconds"] < 90
        root = REPO_ROOT / "services/core-control-plane/src/fdai/delivery/persistence"
        source = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "postgres_ontology.py",
                "postgres_ontology_prepared.py",
                "postgres_ontology_replacement.py",
            )
        }
        print(
            "ONTOLOGY_CAPACITY="
            + json.dumps(
                {
                    "schema_version": "1.0.0",
                    "profile": "synthetic-one-to-many",
                    "publication": publication,
                    "objects": count,
                    "links": count - 1,
                    "padding_bytes": padding,
                    "initial_seconds": durations[0],
                    "replay_seconds": durations[1],
                    "initial_lock_seconds": occupancy[0],
                    "replay_lock_seconds": occupancy[1],
                    "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    * (1 if sys.platform == "darwin" else 1024),
                    "source_sha256": source,
                    "provider_calls": 0,
                    "restart": restart,
                },
                sort_keys=True,
            )
        )


async def test_isolated_graph_query_limits_relationships(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fdai.delivery.persistence.postgres_ontology_graph.MAX_ONTOLOGY_QUERY_LINKS", 1
    )
    async with _isolated_replacement_store() as store:
        objects = (
            _review_object("case"),
            _review_object("check-a", "ReviewCheck"),
            _review_object("check-b", "ReviewCheck"),
        )
        links = tuple(
            OntologyLinkRecord(
                link_type="contains_check",
                from_id="case",
                to_id=identifier,
            )
            for identifier in ("check-a", "check-b")
        )
        await store.replace_subgraph(objects=objects, links=links)
        result = await store.query_objects(limit=10)
        assert len(result.objects) == 3
        assert len(result.links) == 1
        assert result.truncated is True


async def test_isolated_replacement_rejects_cardinality_and_stale_revision_atomically() -> None:
    async with _isolated_replacement_store() as store:
        originals = (_review_object("case-a"), _review_object("check", "ReviewCheck"))
        link = OntologyLinkRecord(link_type="contains_check", from_id="case-a", to_id="check")
        await store.replace_subgraph(objects=originals, links=(link,))
        before = await store.query_objects()
        with pytest.raises(OntologyInstanceValidationError, match="cardinality"):
            await store.replace_subgraph(
                objects=(_review_object("case-b"),),
                links=(replace(link, from_id="case-b"),),
            )
        assert await store.get_object("case-b") is None
        with pytest.raises(OntologyInstanceValidationError, match="revision fence"):
            await store.replace_subgraph(objects=originals, links=())
        assert await store.query_objects() == before


async def test_isolated_graph_read_does_not_mix_concurrent_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _isolated_replacement_store() as store:
        await store.replace_subgraph(objects=(_review_object("case-a"),), links=())
        from fdai.delivery.persistence import postgres_ontology_graph

        load_links = postgres_ontology_graph._links_within
        entered = False

        async def replace_between_reads(connection, identifiers, *, releases):
            nonlocal entered
            if not entered:
                entered = True
                await store.replace_subgraph(
                    objects=(_review_object("case-b"),), links=(), previous_object_ids=("case-a",)
                )
                cursor = await connection.execute("SELECT id FROM ontology_resource ORDER BY id")
                assert [row["id"] for row in await cursor.fetchall()] == ["case-a"]
            return await load_links(connection, identifiers, releases=releases)

        monkeypatch.setattr(postgres_ontology_graph, "_links_within", replace_between_reads)
        result = await store.query_objects()
        assert [record.id for record in result.objects] == ["case-a"]
        assert [record.id for record in (await store.query_objects()).objects] == ["case-b"]


async def test_isolated_delivery_reader_retains_superseded_pending_generation() -> None:
    from datetime import UTC, datetime

    from fdai.delivery.inventory_configuration_events import (
        configuration_delivery_key,
        configuration_delivery_record,
        configuration_projection_record,
    )
    from fdai.delivery.inventory_sync_models import PromotedInventoryObservation
    from fdai.delivery.persistence.postgres_inventory_delivery import (
        PostgresInventoryDeliveryReader,
    )
    from fdai.delivery.persistence.postgres_inventory_snapshot import (
        PostgresInventorySnapshotStoreConfig,
    )
    from psycopg.types.json import Jsonb

    async with _isolated_replacement_store() as store:
        observation = PromotedInventoryObservation(
            generation="older-generation",
            resources=(),
            links=(),
            complete=True,
            recorded_at=datetime(2026, 9, 20, tzinfo=UTC),
        )
        key = configuration_delivery_key(observation.generation)
        newer = replace(observation, generation="newer-unpublished")
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_snapshot "
                "(id TEXT PRIMARY KEY, completed_at TIMESTAMPTZ, scopes JSONB);"
                "CREATE TABLE inventory_snapshot_resource (snapshot_id TEXT, resource_id TEXT, "
                "resource_type TEXT, props JSONB, provider_ref TEXT, last_seen TIMESTAMPTZ)"
            )
            await connection.execute(
                "INSERT INTO inventory_snapshot VALUES (%s, %s, %s)",
                (observation.generation, observation.recorded_at, Jsonb(["scope-example"])),
            )
        await store.replace_subgraph(
            objects=(),
            links=(),
            _state_updates={
                key: configuration_delivery_record(observation),
                key + ":projection": configuration_projection_record(
                    observation,
                    ontology_release_digest="sha256:" + "a" * 64,
                    manifest_digest="sha256:" + "b" * 64,
                ),
                configuration_delivery_key(newer.generation): configuration_delivery_record(newer),
            },
        )
        reader = PostgresInventoryDeliveryReader(
            config=PostgresInventorySnapshotStoreConfig(dsn=store._config.dsn),
            scope_refs=("scope-example",),
        )
        assert await reader.load_next() == observation
        wrong_scope = PostgresInventoryDeliveryReader(
            config=PostgresInventorySnapshotStoreConfig(dsn=store._config.dsn),
            scope_refs=("different-scope",),
        )
        with pytest.raises(ValueError, match="scope changed"):
            await wrong_scope.load_next()
        async with await store._connect() as connection:
            await connection.execute(
                "UPDATE state_kv SET value=%s WHERE key=%s",
                (Jsonb(configuration_delivery_record(observation, completed=True)), key),
            )
        assert await reader.load_next() is None


async def test_isolated_replacement_handles_batched_high_fanout() -> None:
    async with _isolated_replacement_store() as store:
        objects = (
            _review_object("case"),
            *(_review_object(f"check-{index:04}", "ReviewCheck") for index in range(1200)),
        )
        links = tuple(
            OntologyLinkRecord(
                link_type="contains_check",
                from_id="case",
                to_id=record.id,
            )
            for record in objects[1:]
        )
        await store.replace_subgraph(objects=objects, links=links)
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT (SELECT COUNT(*) FROM ontology_resource) AS objects, "
                "(SELECT COUNT(*) FROM ontology_link) AS links"
            )
            assert await cursor.fetchone() == {"objects": 1201, "links": 1200}


async def test_postgres_atomic_create_deduplicates_concurrent_identity() -> None:
    _requires_live_db()
    _upgrade_head()
    store = _store()
    suffix = uuid.uuid4().hex
    record = OntologyObjectRecord(
        id=f"review-{suffix}",
        object_type="ReviewCase",
        properties={"id": f"review-{suffix}", "status": "open"},
    )

    results = await asyncio.gather(*(store.create_object_if_absent(record) for _ in range(8)))

    created = tuple(item for item in results if item is not None)
    assert len(created) == 1
    assert created[0].revision == 1
    assert sum(item is None for item in results) == 7
    await store.delete_object(record.id)


async def test_postgres_ontology_round_trip_and_traversal() -> None:
    _requires_live_db()
    _upgrade_head()
    store = _store()
    suffix = uuid.uuid4().hex
    review_id = f"review-{suffix}"
    check_id = f"check-{suffix}"
    review = await store.upsert_object(
        OntologyObjectRecord(
            id=review_id,
            object_type="ReviewCase",
            properties={"id": review_id, "status": "open"},
        )
    )
    updated = await store.upsert_object(
        OntologyObjectRecord(
            id=review_id,
            object_type="ReviewCase",
            properties={"id": review_id, "status": "in_review"},
        ),
        expected_revision=review.revision,
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id=check_id,
            object_type="ReviewCheck",
            properties={"id": check_id, "status": "blocked"},
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(
            link_type="contains_check",
            from_id=review_id,
            to_id=check_id,
        )
    )

    graph = await store.traverse(root_ids=(review_id,), max_depth=1)
    selected = await store.query_objects(
        object_types=("ReviewCheck",), property_equals={"status": "blocked"}
    )
    selected_in = await store.query_objects(
        object_types=("ReviewCheck",),
        property_text_in={"status": ("blocked", "ready")},
    )
    root_limited = await store.traverse(root_ids=(check_id, review_id), limit=1)
    exact_root_limit = await store.traverse(root_ids=(check_id,), limit=1)
    deduplicated_roots = await store.traverse(
        root_ids=(f"missing-{suffix}", check_id, check_id), limit=1
    )

    assert updated.revision == 2
    assert {item.id for item in graph.objects} == {review_id, check_id}
    assert len(graph.links) == 1
    assert any(item.id == check_id for item in selected.objects)
    assert any(item.id == check_id for item in selected_in.objects)
    assert [item.id for item in root_limited.objects] == [check_id]
    assert root_limited.truncated is True
    assert [item.id for item in exact_root_limit.objects] == [check_id]
    assert exact_root_limit.truncated is False
    assert [item.id for item in deduplicated_roots.objects] == [check_id]
    assert deduplicated_roots.truncated is False


async def test_postgres_inventory_coverage_scopes_reconciliation_markers() -> None:
    if os.environ.get("FDAI_SERVICE_MIGRATIONS_READY") != "1":
        pytest.skip("service-owned migrations are not ready")
    connection = await psycopg.AsyncConnection.connect(
        _requires_live_db(),
        autocommit=True,
        row_factory=dict_row,
    )
    try:
        await connection.execute(
            "CREATE TEMP TABLE inventory_snapshot ("
            "id TEXT PRIMARY KEY, scopes JSONB NOT NULL, "
            "metadata JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "started_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        await connection.execute(
            "CREATE TEMP TABLE inventory_active "
            "(singleton BOOLEAN PRIMARY KEY, snapshot_id TEXT NOT NULL)"
        )
        await connection.execute(
            "CREATE TEMP TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL)"
        )
        await connection.execute(
            "INSERT INTO inventory_snapshot (id, scopes) "
            "VALUES ('generation-2', '[\"scope-a\"]'::jsonb)"
        )
        await connection.execute(
            "INSERT INTO inventory_active (singleton, snapshot_id) VALUES (TRUE, 'generation-2')"
        )
        for key, value in (
            (
                "inventory-ontology:status",
                '{"status":"available","generation":"generation-2","complete":true}',
            ),
            (
                "inventory-ontology:manifest",
                '{"generation":"generation-2","complete":true,'
                '"relationship_complete":true,"dropped_reasons":[]}',
            ),
            (
                "inventory-relationship-reconciliation:scope-b",
                '{"observed_at":"2026-09-01T00:00:00Z"}',
            ),
        ):
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                (key, value),
            )

        unrelated_complete, generation = await postgres_ontology._resource_graph_source_coverage(  # noqa: SLF001
            connection,
            (),
            requires_resource_coverage=True,
        )
        await connection.execute(
            "INSERT INTO state_kv (key, value) "
            "VALUES ('inventory-relationship-reconciliation:scope-a', "
            '\'{"observed_at":"2026-09-01T00:00:00Z"}\'::jsonb)'
        )
        related_complete, _ = await postgres_ontology._resource_graph_source_coverage(  # noqa: SLF001
            connection,
            (),
            requires_resource_coverage=True,
        )
        object_only_complete, _ = await postgres_ontology._resource_graph_source_coverage(  # noqa: SLF001
            connection,
            (),
            requires_resource_coverage=True,
            expresses_relationships=False,
        )
    finally:
        await connection.close()

    assert unrelated_complete is True
    assert related_complete is False
    assert object_only_complete is True
    assert generation == "generation-2"


async def test_postgres_replace_subgraph_removes_prior_owned_records() -> None:
    _requires_live_db()
    _upgrade_head()
    store = _store()
    suffix = uuid.uuid4().hex
    review_id = f"review-{suffix}"
    check_id = f"check-{suffix}"
    review = OntologyObjectRecord(
        id=review_id,
        object_type="ReviewCase",
        properties={"id": review_id, "status": "open"},
    )
    check = OntologyObjectRecord(
        id=check_id,
        object_type="ReviewCheck",
        properties={"id": check_id, "status": "blocked"},
    )
    link = OntologyLinkRecord(
        link_type="contains_check",
        from_id=review_id,
        to_id=check_id,
    )
    await store.replace_subgraph(objects=(review, check), links=(link,))
    stored_review = await store.get_object(review_id)
    assert stored_review is not None

    await store.replace_subgraph(
        objects=(
            OntologyObjectRecord(
                id=review.id,
                object_type=review.object_type,
                properties=review.properties,
                revision=stored_review.revision,
            ),
        ),
        links=(),
        previous_object_ids=(review_id, check_id),
        previous_link_keys=((review_id, "contains_check", check_id),),
    )

    assert await store.get_object(review_id) is not None
    assert await store.get_object(check_id) is None
    graph = await store.traverse(root_ids=(review_id,), max_depth=1)
    assert graph.links == ()


async def test_postgres_replace_subgraph_rejects_batch_cardinality_atomically() -> None:
    _requires_live_db()
    _upgrade_head()
    store = _store()
    suffix = uuid.uuid4().hex
    review_ids = (f"review-a-{suffix}", f"review-b-{suffix}")
    check_id = f"check-{suffix}"
    objects = (
        *(
            OntologyObjectRecord(
                id=review_id,
                object_type="ReviewCase",
                properties={"id": review_id, "status": "open"},
            )
            for review_id in review_ids
        ),
        OntologyObjectRecord(
            id=check_id,
            object_type="ReviewCheck",
            properties={"id": check_id, "status": "ready"},
        ),
    )
    links = tuple(
        OntologyLinkRecord(
            link_type="contains_check",
            from_id=review_id,
            to_id=check_id,
        )
        for review_id in review_ids
    )

    with pytest.raises(OntologyInstanceValidationError, match="one_to_many cardinality"):
        await store.replace_subgraph(objects=objects, links=links)

    assert [await store.get_object(record.id) for record in objects] == [None, None, None]


async def test_postgres_upsert_and_replace_share_cardinality_lock() -> None:
    _requires_live_db()
    _upgrade_head()
    store = _store()
    suffix = uuid.uuid4().hex
    review_ids = (f"review-a-{suffix}", f"review-b-{suffix}")
    check_id = f"check-{suffix}"
    for review_id in review_ids:
        await store.upsert_object(
            OntologyObjectRecord(
                id=review_id,
                object_type="ReviewCase",
                properties={"id": review_id, "status": "open"},
            )
        )
    await store.upsert_object(
        OntologyObjectRecord(
            id=check_id,
            object_type="ReviewCheck",
            properties={"id": check_id, "status": "ready"},
        )
    )
    links = tuple(
        OntologyLinkRecord(
            link_type="contains_check",
            from_id=review_id,
            to_id=check_id,
        )
        for review_id in review_ids
    )

    results = await asyncio.gather(
        store.upsert_link(links[0]),
        store.replace_subgraph(objects=(), links=(links[1],)),
        return_exceptions=True,
    )

    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], OntologyInstanceValidationError)
    assert "one_to_many cardinality" in str(errors[0])
    graph = await store.traverse(root_ids=(*review_ids, check_id), max_depth=1)
    assert len(graph.links) == 1
