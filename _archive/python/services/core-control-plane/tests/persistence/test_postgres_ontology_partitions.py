"""Exact storage partition coverage must never infer provider or ownership scope."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fdai.delivery.persistence.postgres_ontology_partitions import (
    partition_descriptor,
    prepare_partition_set,
    validate_partition_set,
)
from fdai.shared.providers.ontology_instance import OntologyInstanceValidationError

from tests.persistence.test_postgres_ontology_instance import (
    _isolated_replacement_store,
    _review_object,
)
from tests.persistence.test_postgres_ontology_transition import (
    _install,
    activate_versioned_graph,
    materialize_legacy_graph,
)


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "empty",
        "overlap",
        "order",
        "count",
        "bool",
        "owner",
        "digest",
        "missing",
        "range",
        "key",
        "kind",
    ],
)
def test_partition_set_requires_complete_ordered_owner_coverage(defect):
    chunks = (
        '{"kind":"objects","records":[{"id":"a"},{"id":"b"}]}',
        '{"kind":"objects","records":[{"id":"c"}]}',
        '{"kind":"links","records":[{"from_id":"a","link_type":"contains","to_id":"c"}]}',
    )
    if defect == "empty":
        assert prepare_partition_set(())["partitions"] == []
        return
    descriptors = [partition_descriptor(chunk) for chunk in chunks]
    value = deepcopy(prepare_partition_set(chunks))
    if defect == "overlap":
        value["partitions"][1]["first"] = ["b"]
    elif defect == "order":
        value["partitions"].reverse()
    elif defect == "count":
        value["object_count"] = 4
    elif defect == "bool":
        value["link_count"] = True
    elif defect == "owner":
        value["ownership"] = "provider-shard"
    elif defect == "digest":
        value["partitions"][0]["digest"] = "sha256:" + "a" * 64
    elif defect == "missing":
        value["partitions"].pop()
    elif defect == "range":
        value["partitions"][0]["first"] = ["z"]
    elif defect == "key":
        value["partitions"][0]["first"] = [1]
    elif defect == "kind":
        value["partitions"][0]["kind"] = "other"
    if defect == "none":
        validate_partition_set(value, descriptors)
    else:
        with pytest.raises(OntologyInstanceValidationError):
            validate_partition_set(value, descriptors)


async def test_durable_preparation_changed_after_load_cannot_publish(monkeypatch):
    from fdai.delivery.persistence import postgres_ontology

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await activate_versioned_graph(connection)
        original = postgres_ontology.prepare_inventory_version

        async def corrupt(*args, **kwargs):
            prepared = await original(*args, **kwargs)
            async with await store._connect() as connection:
                await connection.execute(
                    "UPDATE state_kv SET value=value || "
                    "jsonb_build_object('schema_version','2.0.0') "
                    "WHERE starts_with(key,'ontology-version-prepared:')"
                )
            return prepared

        monkeypatch.setattr(postgres_ontology, "prepare_inventory_version", corrupt)
        with pytest.raises(OntologyInstanceValidationError, match="changed before publication"):
            await store.replace_subgraph_with_state(
                objects=(_review_object("case"),),
                links=(),
                previous_object_ids=(),
                previous_link_keys=(),
                state_updates={},
                expected_active_generation="example-generation",
            )
        assert await store.get_object("case") is None


async def test_version_transition_preserves_production_columns_and_prepared_reader():
    from dataclasses import replace

    from fdai.shared.providers.ontology_instance import OntologyLinkRecord

    async with _isolated_replacement_store() as store:
        async with await store._connect() as connection:
            await connection.execute(
                "ALTER TABLE ontology_resource "
                "ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();"
                "ALTER TABLE ontology_link ADD COLUMN id UUID NOT NULL DEFAULT gen_random_uuid(),"
                "ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();"
                "ALTER TABLE ontology_link ADD CONSTRAINT link_identity_unique UNIQUE (id);"
                "CREATE TABLE ontology_finding (id UUID DEFAULT gen_random_uuid(),"
                "resource_ref TEXT REFERENCES ontology_resource(id));"
            )
        await store.replace_subgraph(
            objects=(_review_object("case"), _review_object("check", "ReviewCheck")),
            links=(OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="check"),),
        )
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT id,created_at FROM ontology_link")
            original_link = await cursor.fetchone()
            await _install(connection)
        async with await store._connect() as reader:
            await reader.execute(
                "PREPARE retained_read AS SELECT properties FROM ontology_resource WHERE id='case'"
            )
            await reader.commit()
            async with await store._connect() as connection:
                await activate_versioned_graph(connection)
            await store.upsert_object(
                replace(_review_object("case"), properties={"id": "case", "status": "updated"}),
                expected_revision=1,
            )
            cursor = await reader.execute("EXECUTE retained_read")
            assert (await cursor.fetchone())["properties"]["status"] == "updated"
            await reader.commit()
        async with await store._connect() as connection:
            await materialize_legacy_graph(connection)
            cursor = await connection.execute("SELECT id,created_at FROM ontology_link")
            assert await cursor.fetchone() == original_link
            await connection.execute("INSERT INTO ontology_finding(resource_ref) VALUES ('case')")


async def test_committed_retention_keeps_pending_preparation_input_partitions():
    from fdai.delivery.persistence.postgres_ontology_prepared import _digest, _encode
    from fdai.delivery.persistence.postgres_ontology_snapshot import _prune_committed_snapshots
    from psycopg.types.json import Jsonb

    assert any(
        isinstance(value, str) and "ontology-version-prepared:" in value
        for value in _prune_committed_snapshots.__code__.co_consts
    )
    async with _isolated_replacement_store() as store:
        chunk = {"kind": "objects", "records": [{"id": "retained"}]}
        chunk_digest = _digest(_encode(chunk, limit=10000))
        manifest = {"chunks": [chunk_digest]}
        manifest_digest = _digest(_encode(manifest, limit=10000))
        async with await store._connect() as connection:
            await connection.execute(
                "INSERT INTO state_kv (key,value,updated_at) VALUES "
                "(%s,%s,NOW()-INTERVAL '2 hours'),(%s,%s,NOW()-INTERVAL '2 hours')",
                (
                    "ontology-prepared:" + chunk_digest,
                    Jsonb(chunk),
                    "ontology-prepared:" + manifest_digest,
                    Jsonb(manifest),
                ),
            )
            await connection.execute(
                "INSERT INTO state_kv (key,value) VALUES (%s,%s)",
                (
                    "ontology-version-prepared:" + manifest_digest,
                    Jsonb({"prepared_digest": manifest_digest}),
                ),
            )
            for index in range(9):
                receipt = {"prepared_digest": "sha256:" + str(index) * 64, "partitions": []}
                if index == 0:
                    receipt = {
                        "prepared_digest": manifest_digest,
                        "partitions": [{"digest": chunk_digest}],
                    }
                await connection.execute(
                    "INSERT INTO state_kv (key,value,updated_at) "
                    "VALUES (%s,%s,NOW()+%s*INTERVAL '1 second')",
                    ("ontology-committed:sha256:" + str(index) * 64, Jsonb(receipt), index),
                )
            assert (
                await _prune_committed_snapshots(connection, current_digest="sha256:" + "8" * 64)
                == 1
            )
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM state_kv WHERE key=ANY(%s::text[])",
                (["ontology-prepared:" + chunk_digest, "ontology-prepared:" + manifest_digest],),
            )
            assert (await cursor.fetchone())["count"] == 2


async def test_unchanged_graph_preparations_have_independent_metadata_capacity(monkeypatch):
    from dataclasses import replace

    from fdai.delivery.persistence import postgres_ontology

    class ProcessLost(BaseException):
        pass

    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("case"))
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
        for index in range(17):
            error = ProcessLost if index < 16 else OntologyInstanceValidationError
            with pytest.raises(error):
                await store.replace_subgraph_with_state(
                    objects=(replace(_review_object("case"), revision=1),),
                    links=(),
                    previous_object_ids=("case",),
                    previous_link_keys=(),
                    state_updates={"example:state": {"attempt": index}},
                    expected_active_generation="example-generation",
                )
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM state_kv "
                "WHERE starts_with(key,'ontology-version-prepared:')"
            )
            assert (await cursor.fetchone())["count"] == 16
            cursor = await connection.execute(
                "SELECT count(*) AS count FROM ontology_graph_version"
            )
            assert (await cursor.fetchone())["count"] == 1
