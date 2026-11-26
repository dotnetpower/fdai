"""Synthetic end-to-end collection and versioned publication under the process ceiling."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial

from fdai.delivery.inventory_process_budget import apply_inventory_memory_limit
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.persistence.postgres_inventory_prepared import (
    load_prepared_candidate,
    seal_candidate,
)
from fdai.delivery.persistence.postgres_inventory_resume import load_unfinished_collection
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest, InventorySource
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from tests.persistence.test_postgres_inventory_chunks import _database
from tests.persistence.test_postgres_ontology_instance import (
    _isolated_replacement_store,
    _type,
)
from tests.persistence.test_postgres_ontology_transition import _install, activate_versioned_graph


async def _measure(collection_dsn, graph_dsn, count):
    import resource
    import time

    from fdai.delivery.persistence import (
        PostgresOntologyInstanceStore,
        PostgresOntologyInstanceStoreConfig,
    )

    limit = apply_inventory_memory_limit()
    graph = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=graph_dsn),
        object_types=(_type("Resource"),),
        link_types=(),
    )
    config = PostgresInventorySnapshotStoreConfig(dsn=collection_dsn)
    store = PostgresInventorySnapshotStore(config=config)
    complete = []

    class Lock:
        @asynccontextmanager
        async def acquire(self, unused):
            yield

    class Source:
        async def full_snapshot(self, since=None):
            assert since is None
            for offset in range(0, count, 500):
                yield InventoryBatch(
                    resources=tuple(
                        ResourceRecord(
                            f"resource-{index:06}",
                            "compute.vm",
                            {"id": f"resource-{index:06}", "status": "open"},
                        )
                        for index in range(offset, min(count, offset + 500))
                    )
                )
            yield InventoryBatch(final=True)

    async def publish(observation):
        async with await graph._connect() as connection:
            await connection.execute(
                "INSERT INTO inventory_active VALUES(TRUE,%s) "
                "ON CONFLICT(singleton) DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id",
                (observation.generation,),
            )
        await graph.replace_subgraph_with_state(
            objects=tuple(
                OntologyObjectRecord(
                    id=item.resource_id, object_type="Resource", properties=item.props
                )
                for item in observation.resources
            ),
            links=(),
            previous_object_ids=(),
            previous_link_keys=(),
            state_updates={
                "inventory-ontology:manifest": {
                    "generation": observation.generation,
                    "object_ids": [item.resource_id for item in observation.resources],
                    "link_keys": [],
                }
            },
            expected_active_generation=observation.generation,
        )
        complete.append(observation.generation)

    started = time.perf_counter()
    await InventorySyncCoordinator(
        store=store,
        run_lock=Lock(),
        collection_loader=partial(load_unfinished_collection, config),
        candidate_loader=partial(load_prepared_candidate, config),
        candidate_preparer=partial(seal_candidate, config),
        promotion_observer=publish,
    ).run(
        (
            InventorySource(
                name="synthetic-capacity",
                inventory=Source(),
                manifest=InventoryCoverageManifest(
                    source="synthetic-capacity",
                    scopes=("synthetic",),
                    resource_types=("compute.vm",),
                    started_at=datetime.now(UTC),
                ),
            ),
        )
    )
    async with await graph._connect() as connection:
        cursor = await connection.execute("SELECT count(*) AS count FROM ontology_resource")
        assert (await cursor.fetchone())["count"] == count
    assert len(complete) == 1
    return {
        "objects": count,
        "seconds": time.perf_counter() - started,
        "address_space_limit_bytes": limit,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "provider_calls": 0,
    }


async def test_inventory_to_versioned_graph_capacity():
    count = int(os.environ.get("FDAI_ONTOLOGY_CAPACITY_ROWS", "1000"))
    assert 1 <= count <= 50000
    async with _database() as (collection, unused, context), _isolated_replacement_store() as graph:
        async with await collection._connect() as connection:
            await connection.execute(
                "ALTER TABLE inventory_snapshot ADD COLUMN resource_count INTEGER,"
                "ADD COLUMN link_count INTEGER; CREATE TABLE inventory_active "
                "(singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT,updated_at TIMESTAMPTZ); "
                "CREATE TABLE inventory_realtime_resource (observed_at TIMESTAMPTZ); "
                "CREATE TABLE inventory_realtime_link (observed_at TIMESTAMPTZ)"
            )
        async with await graph._connect() as connection:
            await _install(connection)
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT)"
            )
            await activate_versioned_graph(connection)
        code = """
import asyncio,json,os,runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(os.environ['CAPACITY_FILE']).parents[2]))
namespace=runpy.run_path(os.environ['CAPACITY_FILE'])
print(json.dumps(asyncio.run(namespace['_measure'](os.environ['COLLECTION_DSN'],
    os.environ['GRAPH_DSN'],int(os.environ['CAPACITY_ROWS'])))))
"""
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env={
                **os.environ,
                "CAPACITY_FILE": __file__,
                "COLLECTION_DSN": collection._config.dsn,
                "GRAPH_DSN": graph._config.dsn,
                "CAPACITY_ROWS": str(count),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, (
            stderr.decode()
            .replace(collection._config.dsn, "<collection-dsn>")
            .replace(graph._config.dsn, "<graph-dsn>")
        )
        print("INVENTORY_PUBLICATION_CAPACITY=" + json.dumps(json.loads(stdout), sort_keys=True))
