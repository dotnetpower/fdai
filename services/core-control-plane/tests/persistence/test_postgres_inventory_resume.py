"""Unfinished source recovery must replay identities before final coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.delivery.inventory_collection import InventoryStreamError
from fdai.delivery.persistence.postgres_inventory_resume import load_unfinished_collection
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest

from tests.persistence.test_postgres_inventory_chunks import _database


@pytest.mark.parametrize(
    "condition",
    [
        "same",
        "changed",
        "missing",
        "partial",
        "context",
        "expired",
        "staged_changed",
        "uncheckpointed",
    ],
)
async def test_unfinished_candidate_requires_full_source_revalidation(condition):
    async with _database() as (store, attempt, context):
        resource = ResourceRecord(
            "retained", "compute.vm", {"status": "open"}, last_seen=datetime.now(UTC).isoformat()
        )
        await store.stage_chunk(
            attempt,
            InventoryBatch(resources=(resource,), cursor="opaque-token"),
            context_digest=context,
            sequence=0,
            previous_digest=None,
        )
        manifest = InventoryCoverageManifest(
            source="example-source",
            scopes=("scope-example",),
            resource_types=("compute.vm",),
            metadata={"mapping_revision": "sha256:" + "a" * 64},
        )
        if condition == "context":
            manifest = replace(manifest, metadata={"mapping_revision": "sha256:" + "b" * 64})
        elif condition == "expired":
            async with await store._connect() as connection:
                await connection.execute(
                    "UPDATE inventory_snapshot SET started_at=NOW()-INTERVAL '31 minutes'"
                )
        elif condition in {"staged_changed", "uncheckpointed"}:
            async with await store._connect() as connection:
                if condition == "staged_changed":
                    await connection.execute("UPDATE inventory_snapshot_resource SET props='{}'")
                else:
                    await connection.execute(
                        "INSERT INTO inventory_snapshot_resource "
                        "(snapshot_id,resource_id,resource_type,props) "
                        "VALUES (%s,'uncheckpointed','compute.vm','{}')",
                        (attempt,),
                    )
            with pytest.raises(ValueError, match="differs|uncheckpointed"):
                await load_unfinished_collection(store._config, manifest)
            return
        resumed = await load_unfinished_collection(store._config, manifest)
        if condition in {"context", "expired"}:
            assert resumed is None
            return
        assert resumed.attempt_id == attempt
        assert resumed.checkpoint["cursor"] == "opaque-token"
        if condition == "missing":
            with pytest.raises(InventoryStreamError, match="identity coverage"):
                resumed.revalidate(InventoryBatch(final=True))
        elif condition == "changed":
            with pytest.raises(InventoryStreamError, match="content changed"):
                resumed.revalidate(
                    InventoryBatch(resources=(replace(resource, props={"status": "changed"}),))
                )
        else:
            observed, staging = resumed.revalidate(InventoryBatch(resources=(resource,)))
            assert observed.resources == (resource,)
            assert staging.resources == ()
            if condition == "same":
                resumed.revalidate(InventoryBatch(final=True))
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT status FROM inventory_snapshot WHERE id=%s", (attempt,)
            )
            assert (await cursor.fetchone())["status"] == "collecting"


@pytest.mark.parametrize("condition", ["complete", "partial", "missing", "changed"])
async def test_coordinator_resumes_original_attempt_but_replays_entire_source(condition):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from fdai.delivery.inventory_sync import InventorySyncCoordinator
    from fdai.delivery.operational_activity import ObservedInventorySnapshotStore
    from fdai.shared.providers.inventory_snapshot import (
        InventorySource,
        InventorySourcesExhaustedError,
    )

    class Lock:
        @asynccontextmanager
        async def acquire(self, unused):
            yield

    async with _database() as (store, attempt, context):
        resource = ResourceRecord("retained", "compute.vm", {"status": "open"})
        await store.stage_chunk(
            attempt,
            InventoryBatch(resources=(resource,), cursor="opaque-token"),
            context_digest=context,
            sequence=0,
            previous_digest=None,
        )
        source_manifest = InventoryCoverageManifest(
            source="example-source",
            scopes=("scope-example",),
            resource_types=("compute.vm",),
            metadata={"mapping_revision": "sha256:" + "a" * 64},
        )
        resumed = await load_unfinished_collection(store._config, source_manifest)
        store.begin = AsyncMock(side_effect=AssertionError("must reuse unfinished attempt"))
        store.promote = AsyncMock()
        store.fail = AsyncMock()
        observed = []
        invocations = []

        class Inventory:
            async def full_snapshot(self, since=None):
                invocations.append(since)
                if condition != "missing":
                    yield InventoryBatch(
                        resources=(
                            replace(resource, props={"status": "changed"})
                            if condition == "changed"
                            else resource,
                        )
                    )
                yield InventoryBatch(resources=(ResourceRecord("new", "compute.vm"),))
                if condition != "partial":
                    yield InventoryBatch(final=True)

        async def observe(value):
            observed.append(value)

        observed_store = ObservedInventorySnapshotStore(store=store, publisher=AsyncMock())
        coordinator = InventorySyncCoordinator(
            store=observed_store,
            run_lock=Lock(),
            collection_loader=AsyncMock(return_value=resumed),
            promotion_observer=observe,
        )
        source = InventorySource(
            name="example-source", inventory=Inventory(), manifest=source_manifest
        )
        if condition == "complete":
            result = await coordinator.run((source,))
            assert result.attempt_id == attempt
            assert {item.resource_id for item in observed[0].resources} == {"retained", "new"}
            assert store.promote.await_args.args[1].started_at == resumed.manifest.started_at
            checkpoint = await store.read_chunk_checkpoint(attempt, context_digest=context)
            assert checkpoint["resource_count"] == 2
            assert checkpoint["next_sequence"] == 2
        else:
            with pytest.raises(InventorySourcesExhaustedError):
                await coordinator.run((source,))
            store.promote.assert_not_awaited()
            assert observed == []
        assert invocations == [None]


@pytest.mark.parametrize("stage", ["source", "enrichment"])
async def test_coordinator_enforces_normalized_byte_bound_at_each_retention_stage(
    monkeypatch, stage
):
    from fdai.delivery import inventory_collection
    from fdai.delivery.inventory_sync import InventorySyncCoordinator
    from fdai.shared.providers.inventory_snapshot import InventorySourcesExhaustedError

    from tests.delivery.test_inventory_sync import _Inventory, _source, _Store

    monkeypatch.setattr(inventory_collection, "MAX_COLLECTION_BYTES", 512)
    resource = ResourceRecord(
        "example", "compute.vm", {"padding": "x" * (1000 if stage == "source" else 1)}
    )
    source = _source(
        "example-source",
        _Inventory([InventoryBatch(resources=(resource,)), InventoryBatch(final=True)]),
    )

    class Enricher:
        async def enrich(self, observation):
            return replace(
                observation, resources=(replace(resource, props={"padding": "x" * 1000}),)
            )

    store = _Store()
    with pytest.raises(InventorySourcesExhaustedError, match="partial"):
        await InventorySyncCoordinator(
            store=store, promotion_enricher=Enricher() if stage == "enrichment" else None
        ).run((source,))
    assert store.promoted == []
    assert "byte bound" in store.failed[0][1].message


async def _resume_in_process(dsn, condition):
    from contextlib import asynccontextmanager
    from functools import partial

    from fdai.delivery.inventory_sync import InventorySyncCoordinator
    from fdai.delivery.persistence.postgres_inventory_prepared import seal_candidate
    from fdai.delivery.persistence.postgres_inventory_snapshot import (
        PostgresInventorySnapshotStore,
        PostgresInventorySnapshotStoreConfig,
    )
    from fdai.shared.providers.inventory_snapshot import (
        InventorySource,
        InventorySourcesExhaustedError,
    )

    class Lock:
        @asynccontextmanager
        async def acquire(self, unused):
            yield

    class Inventory:
        async def full_snapshot(self, since=None):
            assert since is None
            if condition != "missing":
                yield InventoryBatch(
                    resources=(
                        ResourceRecord(
                            "retained",
                            "compute.vm",
                            {"status": "changed" if condition == "changed" else "open"},
                        ),
                    )
                )
            yield InventoryBatch(resources=(ResourceRecord("new", "compute.vm"),))
            if condition != "partial":
                yield InventoryBatch(final=True)

    config = PostgresInventorySnapshotStoreConfig(dsn=dsn)
    store = PostgresInventorySnapshotStore(config=config)
    source = InventorySource(
        name="example-source",
        inventory=Inventory(),
        manifest=InventoryCoverageManifest(
            source="example-source",
            scopes=("scope-example",),
            resource_types=("compute.vm",),
            metadata={"mapping_revision": "sha256:" + "a" * 64},
        ),
    )
    try:
        result = await InventorySyncCoordinator(
            store=store,
            run_lock=Lock(),
            collection_loader=partial(load_unfinished_collection, config),
            candidate_preparer=partial(seal_candidate, config),
        ).run((source,))
    except InventorySourcesExhaustedError:
        return {"promoted": False}
    return {"promoted": True, "attempt": result.attempt_id}


@pytest.mark.parametrize("condition", ["complete", "partial", "missing", "changed"])
async def test_unfinished_candidate_recovers_in_new_process_with_real_promotion(condition):
    import asyncio
    import json
    import os
    import sys

    async with _database() as (store, attempt, context):
        async with await store._connect() as connection:
            await connection.execute(
                "ALTER TABLE inventory_snapshot ADD COLUMN resource_count INTEGER, "
                "ADD COLUMN link_count INTEGER;"
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,"
                "snapshot_id TEXT,updated_at TIMESTAMPTZ);"
                "CREATE TABLE inventory_realtime_link (observed_at TIMESTAMPTZ);"
                "CREATE TABLE inventory_realtime_resource (observed_at TIMESTAMPTZ)"
            )
        await store.stage_chunk(
            attempt,
            InventoryBatch(
                resources=(ResourceRecord("retained", "compute.vm", {"status": "open"}),)
            ),
            context_digest=context,
            sequence=0,
            previous_digest=None,
        )
        code = """
import asyncio, json, os, runpy, sys
from pathlib import Path
sys.path.insert(0,str(Path(os.environ['RESUME_TEST_FILE']).parents[2]))
namespace = runpy.run_path(os.environ['RESUME_TEST_FILE'])
from fdai.delivery.inventory_process_budget import apply_inventory_memory_limit
assert apply_inventory_memory_limit() <= 2048*1024*1024
print(json.dumps(asyncio.run(namespace['_resume_in_process'](
    os.environ['RESUME_TEST_DSN'], os.environ['RESUME_TEST_CONDITION']))))
"""
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env={
                **os.environ,
                "RESUME_TEST_FILE": __file__,
                "RESUME_TEST_DSN": store._config.dsn,
                "RESUME_TEST_CONDITION": condition,
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, stderr.decode().replace(
            store._config.dsn, "<disposable-dsn>"
        )
        result = json.loads(stdout)
        assert result["promoted"] is (condition == "complete")
        async with await store._connect() as connection:
            cursor = await connection.execute("SELECT snapshot_id FROM inventory_active")
            active = await cursor.fetchone()
            if condition == "complete":
                assert result["attempt"] == attempt == active["snapshot_id"]
                cursor = await connection.execute(
                    "SELECT resource_count FROM inventory_snapshot WHERE id=%s", (attempt,)
                )
                assert (await cursor.fetchone())["resource_count"] == 2
            else:
                assert active is None
