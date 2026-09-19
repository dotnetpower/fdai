"""Resource chunk boundary tests; PostgreSQL tests use disposable loopback storage."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.inventory_collection import (
    collection_context_digest,
    collection_key,
    resource_chunk,
    resource_chunk_batches,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb


def _batch() -> InventoryBatch:
    return InventoryBatch(
        resources=(ResourceRecord("resource-example", "compute.vm", {"name": "example"}),),
        cursor="opaque-page-two",
    )


def test_resource_chunk_is_content_bound_and_order_stable() -> None:
    batch = _batch()
    arguments = dict(
        attempt_id="attempt-example",
        context_digest="sha256:" + "a" * 64,
        sequence=0,
        previous_digest=None,
    )
    first = resource_chunk(**arguments, batch=batch)
    assert first == resource_chunk(**arguments, batch=batch)
    assert (
        first["digest"]
        != resource_chunk(**arguments, batch=replace(batch, cursor="other-cursor"))["digest"]
    )


@pytest.mark.parametrize(
    "defect", ["final", "duplicate", "truncated", "environment", "nan", "oversize"]
)
def test_resource_chunk_rejects_unsafe_payload(defect: str) -> None:
    batch = _batch()
    if defect == "final":
        batch = replace(batch, final=True)
    elif defect == "duplicate":
        batch = replace(batch, resources=batch.resources * 2)
    else:
        properties = {
            "truncated": {"_truncated": True},
            "environment": {
                "properties": {
                    "template": {
                        "containers": [{"env": [{"name": "example", "value": "synthetic"}]}]
                    }
                }
            },
            "nan": {"value": float("nan")},
            "oversize": {"value": "x" * (1024 * 1024)},
        }[defect]
        batch = replace(batch, resources=(replace(batch.resources[0], props=properties),))
    with pytest.raises(ValueError):
        resource_chunk(
            attempt_id="attempt-example",
            context_digest="sha256:" + "a" * 64,
            sequence=0,
            previous_digest=None,
            batch=batch,
        )


def test_resource_chunk_split_keeps_cursor_on_last_chunk_only() -> None:
    batch = InventoryBatch(
        resources=tuple(
            ResourceRecord(f"resource-{index}", "compute.vm", {"padding": "x" * 10000})
            for index in range(250)
        ),
        cursor="next-provider-page",
    )
    chunks = tuple(resource_chunk_batches(batch))
    assert len(chunks) > 1
    assert all(chunk.cursor is None for chunk in chunks[:-1])
    assert chunks[-1].cursor == batch.cursor
    assert tuple(item for chunk in chunks for item in chunk.resources) == batch.resources


@asynccontextmanager
async def _database() -> AsyncIterator[tuple[PostgresInventorySnapshotStore, str, str]]:
    dsn = os.environ.get("FDAI_ONTOLOGY_TEST_DSN")
    if not dsn:
        pytest.skip("requires disposable loopback FDAI_ONTOLOGY_TEST_DSN")
    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost"}
    schema = "inventory_chunks_" + uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
        await admin.execute(f"CREATE SCHEMA {schema}")
        scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
        try:
            async with await psycopg.AsyncConnection.connect(scoped) as connection:
                await connection.execute(
                    "CREATE TABLE inventory_snapshot "
                    "(id TEXT PRIMARY KEY, status TEXT, source TEXT, "
                    "observation_kind TEXT, scopes JSONB, resource_types JSONB, metadata JSONB, "
                    "started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, "
                    "failure_code TEXT, failure_message TEXT);"
                    "CREATE TABLE inventory_snapshot_resource (snapshot_id TEXT, resource_id TEXT, "
                    "resource_type TEXT NOT NULL, props JSONB, "
                    "provider_ref TEXT, last_seen TIMESTAMPTZ, "
                    "PRIMARY KEY(snapshot_id, resource_id));"
                    "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB, "
                    "updated_at TIMESTAMPTZ DEFAULT NOW())"
                )
            store = PostgresInventorySnapshotStore(
                config=PostgresInventorySnapshotStoreConfig(dsn=scoped)
            )
            manifest = InventoryCoverageManifest(
                source="example-source",
                scopes=("scope-example",),
                resource_types=("compute.vm",),
                started_at=datetime.now(UTC),
                metadata={"mapping_revision": "sha256:" + "a" * 64},
            )
            attempt = await store.begin(manifest)
            yield store, attempt, collection_context_digest(manifest)
        finally:
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")


async def test_chunk_checkpoint_survives_a_new_process_and_replays_idempotently() -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        restarted = PostgresInventorySnapshotStore(config=store._config)
        assert (
            await restarted.stage_chunk(
                attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
            )
            == first
        )
        code = """
import asyncio, json, os
from fdai.delivery.persistence import postgres_inventory_snapshot as snapshot
async def main():
    config=snapshot.PostgresInventorySnapshotStoreConfig(dsn=os.environ['CHUNK_TEST_DSN'])
    store=snapshot.PostgresInventorySnapshotStore(config=config)
    result=await store.read_chunk_checkpoint(
        os.environ['CHUNK_TEST_ATTEMPT'], context_digest=os.environ['CHUNK_TEST_CONTEXT'])
    print(json.dumps({key:result[key] for key in ('next_sequence', 'cursor', 'digest')}))
asyncio.run(main())
"""
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env={
                **os.environ,
                "CHUNK_TEST_DSN": store._config.dsn,
                "CHUNK_TEST_ATTEMPT": attempt,
                "CHUNK_TEST_CONTEXT": context,
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0
        assert json.loads(stdout) == {
            "next_sequence": 1,
            "cursor": _batch().cursor,
            "digest": first["digest"],
        }
        second = InventoryBatch(
            resources=(ResourceRecord("resource-two", "compute.vm"),), cursor="page-three"
        )
        await restarted.stage_chunk(
            attempt, second, context_digest=context, sequence=1, previous_digest=first["digest"]
        )
        checkpoint = await restarted.read_chunk_checkpoint(attempt, context_digest=context)
        assert checkpoint is not None and checkpoint["next_sequence"] == 2


@pytest.mark.parametrize(
    "defect",
    [
        "changed_chunk",
        "sequence_gap",
        "context",
        "predecessor",
        "tampered_cursor",
        "missing_chunk",
        "failed_attempt",
    ],
)
async def test_chunk_rejects_invalid_resume_without_advancing(defect: str) -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        before = await store.read_chunk_checkpoint(attempt, context_digest=context)
        if defect in {"tampered_cursor", "missing_chunk", "failed_attempt"}:
            async with await store._connect() as connection:
                if defect == "tampered_cursor":
                    await connection.execute(
                        "UPDATE state_kv SET value=jsonb_set(value, '{cursor}', '\"altered\"') "
                        "WHERE key=%s",
                        (collection_key(attempt) + ":checkpoint",),
                    )
                elif defect == "missing_chunk":
                    await connection.execute(
                        "DELETE FROM state_kv WHERE key=%s",
                        (collection_key(attempt) + ":chunk:00000000",),
                    )
                else:
                    await connection.execute(
                        "UPDATE inventory_snapshot SET status='failed' WHERE id=%s", (attempt,)
                    )
            with pytest.raises((ValueError, RuntimeError)):
                await store.read_chunk_checkpoint(attempt, context_digest=context)
            return
        with pytest.raises(ValueError):
            await store.stage_chunk(
                attempt,
                replace(_batch(), cursor="changed"),
                context_digest="sha256:" + "b" * 64 if defect == "context" else context,
                sequence=0 if defect == "changed_chunk" else 2 if defect == "sequence_gap" else 1,
                previous_digest=None
                if defect == "changed_chunk"
                else "sha256:" + "b" * 64
                if defect == "predecessor"
                else first["digest"],
            )
        assert await store.read_chunk_checkpoint(attempt, context_digest=context) == before


@pytest.mark.parametrize(
    "defect",
    ["schema", "attempt", "cursor", "bytes", "resources", "missing_chunk", "changed_chunk"],
)
async def test_append_rejects_corrupt_retained_checkpoint(defect: str) -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        key = collection_key(attempt)
        async with await store._connect() as connection:
            if defect == "missing_chunk":
                await connection.execute(
                    "DELETE FROM state_kv WHERE key=%s", (key + ":chunk:00000000",)
                )
            elif defect == "changed_chunk":
                await connection.execute(
                    "UPDATE state_kv SET value=value || %s WHERE key=%s",
                    (Jsonb({"cursor": "changed"}), key + ":chunk:00000000"),
                )
            else:
                change = {
                    "schema": {"schema_version": "unknown"},
                    "attempt": {"attempt_id": "other-attempt"},
                    "cursor": {"cursor": "changed"},
                    "bytes": {"byte_count": 1},
                    "resources": {"resource_count": 2},
                }[defect]
                await connection.execute(
                    "UPDATE state_kv SET value=value || %s WHERE key=%s",
                    (Jsonb(change), key + ":checkpoint"),
                )
        second = InventoryBatch(resources=(ResourceRecord("resource-two", "compute.vm"),))
        with pytest.raises(ValueError):
            await store.stage_chunk(
                attempt, second, context_digest=context, sequence=1, previous_digest=first["digest"]
            )
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) AS total FROM inventory_snapshot_resource "
                "WHERE resource_id='resource-two'"
            )
            assert (await cursor.fetchone())["total"] == 0
            cursor = await connection.execute(
                "SELECT COUNT(*) AS total FROM state_kv WHERE key=%s", (key + ":chunk:00000001",)
            )
            assert (await cursor.fetchone())["total"] == 0


@pytest.mark.parametrize(
    "defect", ["none", "bytes", "resources", "missing_prefix", "changed_prefix", "extra"]
)
async def test_legacy_checkpoint_requires_verified_chain_before_upgrade(defect: str) -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        second = await store.stage_chunk(
            attempt,
            InventoryBatch(resources=(ResourceRecord("resource-two", "compute.vm"),)),
            context_digest=context,
            sequence=1,
            previous_digest=first["digest"],
        )
        key = collection_key(attempt)
        async with await store._connect() as connection:
            change = {"schema_version": "1.0.0"}
            change.update(
                {
                    "bytes": {"byte_count": 1},
                    "resources": {"resource_count": 1},
                    "extra": {"unknown": True},
                }.get(defect, {})
            )
            await connection.execute(
                "UPDATE state_kv SET value=(value - 'content_digest') || %s WHERE key=%s",
                (Jsonb(change), key + ":checkpoint"),
            )
            if defect == "missing_prefix":
                await connection.execute(
                    "DELETE FROM state_kv WHERE key=%s", (key + ":chunk:00000000",)
                )
            elif defect == "changed_prefix":
                await connection.execute(
                    "UPDATE state_kv SET value=value || %s WHERE key=%s",
                    (Jsonb({"cursor": "changed"}), key + ":chunk:00000000"),
                )

        async def append():
            return await store.stage_chunk(
                attempt,
                InventoryBatch(resources=(ResourceRecord("resource-three", "compute.vm"),)),
                context_digest=context,
                sequence=2,
                previous_digest=second["digest"],
            )

        if defect != "none":
            with pytest.raises(ValueError):
                await store.read_chunk_checkpoint(attempt, context_digest=context)
            with pytest.raises(ValueError):
                await append()
        else:
            legacy = await store.read_chunk_checkpoint(attempt, context_digest=context)
            assert legacy["schema_version"] == "1.0.0"
            await append()
            upgraded = await store.read_chunk_checkpoint(attempt, context_digest=context)
            assert upgraded["schema_version"] == "1.1.0"
            assert upgraded["next_sequence"] == 3
            assert upgraded["resource_count"] == 3
            assert upgraded["content_digest"].startswith("sha256:")


async def test_checkpoint_failure_rolls_back_resource_and_chunk() -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        async with await store._connect() as connection:
            await connection.execute(
                "ALTER TABLE state_kv ADD CONSTRAINT reject_second_checkpoint "
                "CHECK (COALESCE((value->>'next_sequence')::int,0)<2)"
            )
        second = InventoryBatch(
            resources=(ResourceRecord("resource-two", "compute.vm"),), cursor="page-three"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            await store.stage_chunk(
                attempt, second, context_digest=context, sequence=1, previous_digest=first["digest"]
            )
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) AS total FROM inventory_snapshot_resource "
                "WHERE resource_id='resource-two'"
            )
            assert (await cursor.fetchone())["total"] == 0
        checkpoint = await store.read_chunk_checkpoint(attempt, context_digest=context)
        assert checkpoint is not None and checkpoint["next_sequence"] == 1


async def test_expired_collection_cannot_read_or_append_checkpoint() -> None:
    async with _database() as (store, attempt, context):
        await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        async with await store._connect() as connection:
            await connection.execute(
                "UPDATE inventory_snapshot SET started_at=NOW()-INTERVAL '31 minutes' WHERE id=%s",
                (attempt,),
            )
        with pytest.raises(ValueError, match="expired"):
            await store.read_chunk_checkpoint(attempt, context_digest=context)
        with pytest.raises(ValueError, match="expired"):
            await store.stage_chunk(
                attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
            )


async def test_chunk_persists_the_frozen_payload_when_caller_mutates_during_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _database() as (store, attempt, context):
        properties = {"name": "original"}
        batch = InventoryBatch(resources=(ResourceRecord("mutable", "compute.vm", properties),))
        connect = store._connect

        async def mutate_before_connection():
            properties["name"] = "changed"
            return await connect()

        monkeypatch.setattr(store, "_connect", mutate_before_connection)
        await store.stage_chunk(
            attempt, batch, context_digest=context, sequence=0, previous_digest=None
        )
        async with await connect() as connection:
            cursor = await connection.execute(
                "SELECT props FROM inventory_snapshot_resource WHERE resource_id='mutable'"
            )
            assert (await cursor.fetchone())["props"] == {"name": "original"}
        batches = [item async for item in store.replay_chunks(attempt, context_digest=context)]
        assert batches[0].resources[0].props == {"name": "original"}


async def test_concurrent_chunk_conflict_has_one_winner() -> None:
    async with _database() as (store, attempt, context):
        results = await asyncio.gather(
            store.stage_chunk(
                attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
            ),
            store.stage_chunk(
                attempt,
                replace(_batch(), cursor="different"),
                context_digest=context,
                sequence=0,
                previous_digest=None,
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ValueError) for result in results) == 1
        checkpoint = await store.read_chunk_checkpoint(attempt, context_digest=context)
        assert checkpoint is not None and checkpoint["next_sequence"] == 1


@pytest.mark.parametrize("corrupt", [False, True])
async def test_chunk_replay_reconstructs_and_verifies_the_entire_chain(corrupt: bool) -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt,
            _batch(),
            context_digest=context,
            sequence=0,
            previous_digest=None,
        )
        second = InventoryBatch(
            resources=(ResourceRecord("second", "compute.vm"),), cursor="third-page"
        )
        await store.stage_chunk(
            attempt, second, context_digest=context, sequence=1, previous_digest=first["digest"]
        )
        restarted = PostgresInventorySnapshotStore(config=store._config)
        if corrupt:
            async with await store._connect() as connection:
                await connection.execute(
                    "UPDATE state_kv SET value=jsonb_set(value, '{cursor}', '\"altered\"') "
                    "WHERE key=%s",
                    (collection_key(attempt) + ":chunk:00000000",),
                )
            with pytest.raises(ValueError, match="content changed"):
                _ = [
                    batch
                    async for batch in restarted.replay_chunks(attempt, context_digest=context)
                ]
        else:
            batches = [
                batch async for batch in restarted.replay_chunks(attempt, context_digest=context)
            ]
            assert batches == [_batch(), second]
            assert all(not batch.final for batch in batches)


@pytest.mark.parametrize("defect", ["cross_chunk_change", "missing_checkpoint", "boolean_sequence"])
async def test_chunk_hardening_prevents_replay_and_cross_chunk_corruption(defect: str) -> None:
    async with _database() as (store, attempt, context):
        first = await store.stage_chunk(
            attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
        )
        key = collection_key(attempt)
        if defect == "cross_chunk_change":
            changed = replace(
                _batch(), resources=(replace(_batch().resources[0], props={"name": "different"}),)
            )
            with pytest.raises(ValueError, match="changed across"):
                await store.stage_chunk(
                    attempt,
                    changed,
                    context_digest=context,
                    sequence=1,
                    previous_digest=first["digest"],
                )
            checkpoint = await store.read_chunk_checkpoint(attempt, context_digest=context)
            assert checkpoint is not None and checkpoint["next_sequence"] == 1
        else:
            async with await store._connect() as connection:
                if defect == "missing_checkpoint":
                    await connection.execute(
                        "DELETE FROM state_kv WHERE key=%s", (key + ":checkpoint",)
                    )
                else:
                    await connection.execute(
                        "UPDATE state_kv SET value=jsonb_set(value, '{sequence}', 'false') "
                        "WHERE key=%s",
                        (key + ":chunk:00000000",),
                    )
            with pytest.raises(ValueError):
                await store.stage_chunk(
                    attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
                )
