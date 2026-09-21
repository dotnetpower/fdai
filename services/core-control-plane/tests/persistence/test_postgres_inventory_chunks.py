"""Resource chunk boundary tests; PostgreSQL tests use disposable loopback storage."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.inventory_collection import (
    collection_context_digest,
    collection_key,
    resource_chunk,
    resource_chunk_batches,
)
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.inventory_sync_models import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
    compute_relationship_coverage,
)
from fdai.delivery.persistence.postgres_inventory_prepared import (
    load_prepared_candidate,
    seal_candidate,
    verify_prepared_candidate,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
    ProviderRelationshipEvidence,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest, InventorySource
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
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
                    "started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, promoted_at TIMESTAMPTZ, "
                    "failure_code TEXT, failure_message TEXT);"
                    "CREATE TABLE inventory_snapshot_resource (snapshot_id TEXT, resource_id TEXT, "
                    "resource_type TEXT NOT NULL, props JSONB, "
                    "provider_ref TEXT, last_seen TIMESTAMPTZ, "
                    "PRIMARY KEY(snapshot_id, resource_id));"
                    "CREATE TABLE inventory_snapshot_link (snapshot_id TEXT, from_id TEXT, "
                    "from_type TEXT, link_type TEXT, to_id TEXT, to_type TEXT, props JSONB, "
                    "PRIMARY KEY(snapshot_id, from_id, link_type, to_id));"
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


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "stage",
        "chunk",
        "resource",
        "manifest",
        "seal",
        "context",
        "expired",
        "missing_row",
        "incomplete",
        "coverage",
        "missing_seal",
        "origin",
        "rich",
        "base",
        "states",
        "future",
        "window",
        "flag_type",
    ],
)
async def test_prepared_candidate_seals_exact_rows_and_rechecks_before_promotion(
    defect: str,
) -> None:
    async with _database() as (store, attempt, context):
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM inventory_snapshot WHERE id=%s", (attempt,)
            )
            row = await cursor.fetchone()
        source = InventoryCoverageManifest(
            source=row["source"],
            scopes=tuple(row["scopes"]),
            resource_types=tuple(row["resource_types"]),
            started_at=row["started_at"],
            metadata=row["metadata"],
        )
        recorded_at = datetime.now(UTC)
        manifest = replace(
            source,
            completed_at=recorded_at,
            metadata={**source.metadata, "projection_complete": True},
        )
        observation = PromotedInventoryObservation(
            generation=attempt,
            resources=_batch().resources,
            links=(),
            complete=defect != "incomplete",
            recorded_at=recorded_at,
        )
        if defect == "rich":
            evidence = ProviderRelationshipEvidence(
                mapping_id="azure.container-app-depends-on-managed-environment",
                mapping_revision="sha256:" + "1" * 64,
                mapping_receipt_ref="catalog-receipt:provider-relationships:azure-arg-v1",
                provider_identity="azure",
                source_identity="azure-resource-graph",
                source_property_path="properties.managedEnvironmentId",
                source_schema_version="azure-resource-graph-resources@2022-10-01",
                source_schema_digest="sha256:" + "2" * 64,
                observed_schema_digest="sha256:" + "2" * 64,
                evidence_method="deterministic-cross-check",
                freshness_ceiling_seconds=21600,
                endpoint_orientation="owner_to_referenced",
                provider_owner_id="app-example",
                observation_receipt_ref="sha256:" + "3" * 64,
            )
            metadata = LinkObservationMetadata(
                state_fact=StateFactMetadata(
                    lane=StateFactLane.OBSERVED,
                    authority=StateFactAuthority.TELEMETRY,
                    source_identity="telemetry.runtime-calls",
                    source_revision="1.0.0",
                    effective_at=recorded_at,
                    recorded_at=recorded_at,
                    evidence_cutoff=recorded_at,
                    freshness_ceiling_seconds=300,
                    completeness=1.0,
                    synthetic=False,
                    evidence_refs=("sha256:" + "4" * 64,),
                ),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory.endpoint-verifier",
                verifier_revision="1.0.0",
                verification_receipt_ref="sha256:" + "5" * 64,
                inventory_generation=attempt,
                mapping_id=evidence.mapping_id,
                mapping_revision=evidence.mapping_revision,
                source_schema_version=evidence.source_schema_version,
                source_schema_digest=evidence.source_schema_digest,
            )
            observation = replace(
                observation,
                resources=tuple(
                    ResourceRecord(identifier, "compute.vm")
                    for identifier in (
                        "Resource-A",
                        "resource-2",
                        "resource_A",
                        "resource-a",
                    )
                ),
                links=(
                    LinkRecord(
                        from_id="Resource-A",
                        from_type="compute.vm",
                        link_type="depends_on",
                        to_id="resource-a",
                        to_type="compute.vm",
                        mapping_evidence=evidence,
                        observation_metadata=metadata,
                        link_props={"provider_relationship_evidence": {"original": True}},
                    ),
                ),
                relationship_drops=(
                    RelationshipDrop(
                        reason=RelationshipDropReason.MISSING_TARGET_ENDPOINT,
                        unavailable_reason=RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION,
                    ),
                ),
                source_states=(
                    InventoryProjectionSourceState(
                        source="example-runtime",
                        status=InventoryProjectionSourceStatus.AVAILABLE,
                        observed_at=recorded_at,
                        reason=None,
                        coverage={"resources": 4},
                        additive=True,
                    ),
                ),
                state_base_generation="previous-example",
                state_base_generation_checked=True,
            )
        manifest = replace(
            manifest,
            metadata={
                **manifest.metadata,
                "relationship_coverage": compute_relationship_coverage(observation).to_metadata(),
                "prepared_candidate_required": True,
                "derived_source_states": [
                    state.to_metadata() for state in observation.source_states if not state.additive
                ],
                "additive_source_states": [
                    state.to_metadata() for state in observation.source_states if state.additive
                ],
                **(
                    {"state_base_generation": observation.state_base_generation}
                    if observation.state_base_generation_checked
                    else {}
                ),
            },
        )
        if defect == "base":
            observation = replace(observation, state_base_generation_checked=True)
        elif defect == "states":
            manifest = replace(
                manifest, metadata={**manifest.metadata, "derived_source_states": [{}]}
            )
        elif defect == "future":
            manifest = replace(manifest, completed_at=recorded_at + timedelta(hours=1))
        elif defect == "window":
            source = replace(source, started_at=source.started_at - timedelta(seconds=1))
            manifest = replace(manifest, started_at=source.started_at)
        elif defect == "flag_type":
            manifest = replace(manifest, metadata={**manifest.metadata, "projection_complete": 1})
        if defect == "coverage":
            manifest = replace(
                manifest, metadata={**manifest.metadata, "relationship_coverage": {}}
            )
        if defect == "origin":
            manifest = replace(
                manifest, metadata={**manifest.metadata, "mapping_revision": "changed"}
            )
        if defect != "missing_row":
            await store.stage(
                attempt,
                InventoryBatch(
                    resources=observation.resources,
                    links=observation.links,
                ),
            )
        if defect in {
            "missing_row",
            "incomplete",
            "coverage",
            "origin",
            "base",
            "states",
            "future",
            "window",
            "flag_type",
        }:
            with pytest.raises(ValueError, match="inventory prepared"):
                await seal_candidate(
                    store._config,
                    source_manifest=source,
                    manifest=manifest,
                    observation=observation,
                )
            return
        seal = await seal_candidate(
            store._config, source_manifest=source, manifest=manifest, observation=observation
        )
        assert (
            await seal_candidate(
                store._config, source_manifest=source, manifest=manifest, observation=observation
            )
            == seal
        )
        loaded = await load_prepared_candidate(store._config, source)
        assert loaded == (
            manifest,
            replace(
                observation,
                resources=tuple(
                    sorted(
                        observation.resources,
                        key=lambda item: item.resource_id,
                    )
                ),
            ),
        )
        assert await load_prepared_candidate(store._config, replace(source, source="other")) is None
        if defect == "stage":
            with pytest.raises(ValueError, match="cannot be changed"):
                await store.stage(attempt, _batch())
            return
        if defect == "chunk":
            with pytest.raises(ValueError, match="cannot be changed"):
                await store.stage_chunk(
                    attempt, _batch(), context_digest=context, sequence=0, previous_digest=None
                )
            return
        async with await store._connect() as connection:
            if defect == "resource":
                await connection.execute(
                    "UPDATE inventory_snapshot_resource SET props='{}' WHERE snapshot_id=%s",
                    (attempt,),
                )
            elif defect == "manifest":
                manifest = replace(manifest, metadata={**manifest.metadata, "substituted": True})
            elif defect == "seal":
                await connection.execute(
                    "UPDATE state_kv SET value=jsonb_set(value, '{graph_digest}', '\"changed\"') "
                    "WHERE key=%s",
                    (collection_key(attempt) + ":prepared",),
                )
            elif defect == "context":
                await connection.execute(
                    "UPDATE inventory_snapshot SET source='other' WHERE id=%s", (attempt,)
                )
            elif defect == "missing_seal":
                await connection.execute(
                    "DELETE FROM state_kv WHERE key=%s", (collection_key(attempt) + ":prepared",)
                )
            elif defect == "expired":
                await connection.execute(
                    "UPDATE inventory_snapshot SET started_at=NOW()-INTERVAL '31 minutes' "
                    "WHERE id=%s",
                    (attempt,),
                )
            if defect in {"none", "rich"}:
                await verify_prepared_candidate(connection, attempt, manifest)
            else:
                with pytest.raises(ValueError, match="inventory"):
                    await verify_prepared_candidate(connection, attempt, manifest)
            cursor = await connection.execute(
                "SELECT status FROM inventory_snapshot WHERE id=%s", (attempt,)
            )
            assert (await cursor.fetchone())["status"] == "collecting"


@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "seal_corrupt",
        "graph_corrupt",
        "configuration",
        "missing_seal",
        "expired",
        "ambiguous",
        "future_start",
        "source",
        "scope",
        "types",
        "base_drift",
    ],
)
async def test_completed_collection_resumes_in_new_process_without_provider_read(outcome) -> None:
    class ProcessLost(BaseException):
        pass

    async with _database() as (store, unused_attempt, context):
        async with await store._connect() as connection:
            await connection.execute(
                "ALTER TABLE inventory_snapshot "
                "ADD COLUMN resource_count INTEGER, ADD COLUMN link_count INTEGER;"
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, "
                "snapshot_id TEXT, updated_at TIMESTAMPTZ);"
                "CREATE TABLE inventory_realtime_link (observed_at TIMESTAMPTZ);"
                "CREATE TABLE inventory_realtime_resource (observed_at TIMESTAMPTZ)"
            )
            cursor = await connection.execute(
                "SELECT * FROM inventory_snapshot WHERE id=%s", (unused_attempt,)
            )
            row = await cursor.fetchone()
        source = InventoryCoverageManifest(
            source=row["source"],
            scopes=tuple(row["scopes"]),
            resource_types=tuple(row["resource_types"]),
            started_at=datetime.now(UTC),
            metadata=row["metadata"],
        )

        class Inventory:
            async def full_snapshot(self):
                yield _batch()
                yield InventoryBatch(final=True)

        class Enricher:
            async def enrich(self, observation):
                return replace(observation, state_base_generation_checked=True)

        retained = []

        async def crash_after_seal(original, manifest, observation):
            await seal_candidate(store._config, original, manifest, observation)
            retained.append(observation.generation)
            raise ProcessLost()

        with pytest.raises(ProcessLost):
            await InventorySyncCoordinator(
                store=store, candidate_preparer=crash_after_seal, promotion_enricher=Enricher()
            ).run((InventorySource(name="example-source", inventory=Inventory(), manifest=source),))
        expected_active = None
        if outcome == "ambiguous":
            with pytest.raises(ProcessLost):
                await InventorySyncCoordinator(
                    store=store, candidate_preparer=crash_after_seal, promotion_enricher=Enricher()
                ).run(
                    (
                        InventorySource(
                            name="example-source", inventory=Inventory(), manifest=source
                        ),
                    )
                )
        elif outcome == "configuration":
            source = replace(source, metadata={**source.metadata, "mapping_revision": "changed"})
        elif outcome == "source":
            source = replace(source, source="other-source")
        elif outcome == "scope":
            source = replace(source, scopes=("other-scope",))
        elif outcome == "types":
            source = replace(source, resource_types=("compute.container-app",))
        else:
            async with await store._connect() as connection:
                if outcome == "seal_corrupt":
                    await connection.execute(
                        "UPDATE state_kv SET "
                        "value=jsonb_set(value, '{graph_digest}', '\"changed\"') "
                        "WHERE key=%s",
                        (collection_key(retained[0]) + ":prepared",),
                    )
                elif outcome == "graph_corrupt":
                    await connection.execute(
                        "UPDATE inventory_snapshot_resource SET props='{}' WHERE snapshot_id=%s",
                        (retained[0],),
                    )
                elif outcome == "missing_seal":
                    await connection.execute(
                        "DELETE FROM state_kv WHERE key=%s",
                        (collection_key(retained[0]) + ":prepared",),
                    )
                elif outcome in {"expired", "future_start"}:
                    offset = timedelta(minutes=-31 if outcome == "expired" else 1)
                    await connection.execute(
                        "UPDATE inventory_snapshot SET started_at=%s WHERE id=%s",
                        (datetime.now(UTC) + offset, retained[0]),
                    )
                elif outcome == "base_drift":
                    await connection.execute(
                        "UPDATE inventory_snapshot SET status='active' WHERE id=%s",
                        (unused_attempt,),
                    )
                    await connection.execute(
                        "INSERT INTO inventory_active VALUES (TRUE, %s, NOW())",
                        (unused_attempt,),
                    )
                    expected_active = unused_attempt
        code = """
import asyncio, json, os
from datetime import UTC, datetime
from functools import partial
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore, PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_prepared import load_prepared_candidate
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest, InventorySource, InventoryObservationKind,
)
class NoProvider:
    def full_snapshot(self):
        raise AssertionError("provider must not be read on sealed recovery")
async def main():
    values=json.loads(os.environ['PREPARED_SOURCE'])
    values['started_at']=datetime.now(UTC)
    values['scopes']=tuple(values['scopes'])
    values['resource_types']=tuple(values['resource_types'])
    values['observation_kind']=InventoryObservationKind(values['observation_kind'])
    values.pop('completed_at')
    source=InventoryCoverageManifest(**values)
    config=PostgresInventorySnapshotStoreConfig(dsn=os.environ['PREPARED_TEST_DSN'])
    observed=[]
    async def observe(record):
        observed.append(record.generation)
    result=await InventorySyncCoordinator(store=PostgresInventorySnapshotStore(config=config),
        candidate_loader=partial(load_prepared_candidate,config),promotion_observer=observe).run(
        (InventorySource(name='example-source',inventory=NoProvider(),manifest=source),))
    print(json.dumps({'attempt_id':result.attempt_id,'observed':observed}))
asyncio.run(main())
"""
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env={
                **os.environ,
                "PREPARED_TEST_DSN": store._config.dsn,
                "PREPARED_SOURCE": json.dumps(asdict(source), default=str),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if outcome == "success":
            assert process.returncode == 0, stderr.decode()
            assert json.loads(stdout) == {"attempt_id": retained[0], "observed": retained}
            assert await store.active_snapshot_id() == retained[0]
        else:
            assert process.returncode != 0
            assert stdout == b""
            assert await store.active_snapshot_id() == expected_active
            if outcome == "base_drift":
                assert "state base generation changed" in stderr.decode()
            elif outcome == "ambiguous":
                assert "ambiguous candidates" in stderr.decode()


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
