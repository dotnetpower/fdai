"""Service-role sensing recovery on isolated loopback PostgreSQL, never runtime state."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from fdai.agents import Heimdall
from fdai.core.readiness import DetectionReadinessDimension
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from tests.agents.test_heimdall_bucket_persistence import (
    BUCKET_PREFIX,
    FlatManifestHeimdall,
    seed_subjects,
)
from tests.agents.test_heimdall_sensing_persistence import (
    STATE,
    LegacySnapshotHeimdall,
    _agent,
    _event,
    _readiness,
    _snapshot,
)
from tests.persistence.test_postgres_state_store import saga_database as _saga_database

pytestmark = pytest.mark.integration


class _RedactedDSN(str):
    def __repr__(self) -> str:
        return "<validation-database>"


@pytest.fixture
async def saga_database() -> AsyncIterator[_RedactedDSN]:
    if os.environ.get("FDAI_SERVICE_MIGRATIONS_READY") != "1":
        pytest.skip("Core-role checkpoint integration requires service-owned migrations")
    database = _saga_database.__wrapped__()
    try:
        yield _RedactedDSN(await anext(database))
    finally:
        await database.aclose()


class ServiceRoleStore(PostgresStateStore):
    writes = 0
    fail_manifest = False

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
        async with super()._connection() as connection:
            await connection.execute("SET ROLE fdai_core")
            try:
                yield connection
            finally:
                await connection.execute("RESET ROLE")

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        if self.fail_manifest and key == STATE:
            raise OSError("injected sensing manifest write failure")
        await super().write_state(key, value)
        self.writes += 1

    async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
        written = await super().write_state_if_absent(key, value)
        self.writes += int(written)
        return written

    async def compare_and_set_state(
        self, key: str, value: Mapping[str, Any], *, expected_revision: int
    ) -> bool:
        written = await super().compare_and_set_state(
            key, value, expected_revision=expected_revision
        )
        self.writes += int(written)
        return written


async def test_service_role_exact_restart_duplicates_and_readiness(
    saga_database: _RedactedDSN,
) -> None:
    assert repr(saga_database) == "<validation-database>"
    # The fixture creates a private schema, and refuses any database except loopback 5433.
    options = conninfo_to_dict(saga_database)["options"]
    schema = options.removeprefix("-c search_path=")
    async with await psycopg.AsyncConnection.connect(saga_database) as connection:
        await connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO fdai_core").format(sql.Identifier(schema))
        )
        await connection.execute("GRANT SELECT, INSERT, UPDATE ON state_kv, audit_log TO fdai_core")
    store = ServiceRoleStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        async with store._connection() as connection:
            role = await (await connection.execute("SELECT current_user AS role")).fetchone()
            assert role == {"role": "fdai_core"}
        agent = _agent(store)
        for index in range(140):
            await agent.on_typed_message("object.event", _event(index, subject=index))
        for index in range(128):
            await agent.on_typed_message("object.event", _event(1_000 + index, subject=0))
        dimensions = tuple(DetectionReadinessDimension)
        for dim in dimensions:
            await agent.on_typed_message("object.event", _readiness("new", dim, 10))
        await agent.on_typed_message("object.event", _readiness("partial", dimensions[0], 20))
        expected = _snapshot(agent)
    finally:
        await store.aclose()
    restarted_store = ServiceRoleStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        restarted = _agent(restarted_store)
        assert await restarted.rehydrate() == 140
        assert _snapshot(restarted) == expected
        assert list(restarted._recent_events) == list(agent._recent_events)
        for _ in range(1_000):
            await restarted.on_typed_message("object.event", _event(1_127, subject=0))
            await restarted.on_typed_message(
                "object.event", _readiness("partial", dimensions[0], 20)
            )
        assert restarted_store.writes == 0
        for dim in dimensions:
            await restarted.on_typed_message("object.event", _readiness("old", dim, 0))
        assert restarted.behavior_snapshot()["detection_readiness:stale_pass"] == 1
        manifest = await restarted_store.read_state(STATE)
        assert manifest is not None
        assert "recent_events" not in manifest
        assert "detection_readiness" not in manifest
    finally:
        await restarted_store.aclose()


async def _allocated_bytes(store: ServiceRoleStore) -> dict[str, int]:
    async with store._connection() as connection:
        cursor = await connection.execute(
            """
            SELECT pg_relation_size(oid) AS heap_bytes,
                   pg_indexes_size(oid) AS index_bytes,
                   CASE WHEN reltoastrelid = 0 THEN 0
                        ELSE pg_total_relation_size(reltoastrelid) END AS toast_bytes,
                   pg_total_relation_size(oid) AS total_bytes,
                   (SELECT count(*) FROM state_kv) AS rows
              FROM pg_class WHERE oid = 'state_kv'::regclass
            """
        )
        row = await cursor.fetchone()
        assert row is not None
        return {key: int(value) for key, value in row.items()}


@asynccontextmanager
async def _measurement_database() -> AsyncIterator[_RedactedDSN]:
    database = _saga_database.__wrapped__()
    try:
        dsn = _RedactedDSN(await anext(database))
        schema = conninfo_to_dict(dsn)["options"].removeprefix("-c search_path=")
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO fdai_core").format(sql.Identifier(schema))
            )
            await connection.execute(
                "GRANT SELECT, INSERT, UPDATE ON state_kv, audit_log TO fdai_core"
            )
            # Compare allocated pages before cleanup, without asynchronous vacuum timing.
            await connection.execute(
                "ALTER TABLE state_kv SET "
                "(autovacuum_enabled=false, toast.autovacuum_enabled=false)"
            )
        yield dsn
    finally:
        await database.aclose()


async def test_service_role_equal_episode_workload_physical_bytes_and_restart() -> None:
    results: dict[str, Any] = {}
    expected_snapshots: dict[str, dict[str, Any]] = {}
    for name, agent_type in (("before", LegacySnapshotHeimdall), ("after", Heimdall)):
        async with _measurement_database() as database:
            store = ServiceRoleStore(config=PostgresStateStoreConfig(dsn=database))
            try:
                initial = await _allocated_bytes(store)
                agent = _agent(store, agent_type=agent_type)
                for index in range(140):
                    await agent.on_typed_message("object.event", _event(index, subject=index))
                for index in range(128):
                    await agent.on_typed_message("object.event", _event(1_000 + index, subject=0))
                for _ in range(1_000):
                    await agent.on_typed_message("object.event", _event(1_127, subject=0))
                expected_snapshots[name] = _snapshot(agent)
                final = await _allocated_bytes(store)
                results[name] = {
                    "writes": store.writes,
                    "allocated": final,
                    "growth": {
                        key: final[key] - initial[key]
                        for key in ("heap_bytes", "index_bytes", "toast_bytes", "total_bytes")
                    },
                }
            finally:
                await store.aclose()
            restarted_store = ServiceRoleStore(config=PostgresStateStoreConfig(dsn=database))
            try:
                restarted = _agent(restarted_store)
                assert await restarted.rehydrate() == 140
                assert _snapshot(restarted) == expected_snapshots[name]
                same_order = list(restarted._recent_events) == list(agent._recent_events)
                results[name]["restart_order_preserved"] = same_order
                if name == "after":
                    assert same_order
                assert restarted_store.writes == 0
            finally:
                await restarted_store.aclose()
    assert expected_snapshots["before"] == expected_snapshots["after"]
    assert results["after"]["allocated"]["rows"] == results["before"]["allocated"]["rows"] + 64
    assert results["after"]["writes"] < results["before"]["writes"]
    results["scope"] = "isolated state_kv allocation, autovacuum disabled, no WAL attribution"
    print(json.dumps(results, sort_keys=True))


async def test_service_role_failed_manifest_restart_rejects_mixed_checkpoint() -> None:
    async with _measurement_database() as database:
        store = ServiceRoleStore(config=PostgresStateStoreConfig(dsn=database))
        try:
            agent = _agent(store)
            for index in range(3):
                await agent.on_typed_message("object.event", _event(index))
            committed = await store.read_state(STATE)
            store.fail_manifest = True
            with pytest.raises(OSError, match="injected sensing manifest"):
                await agent.on_typed_message("object.event", _event(3))
            assert await store.read_state(STATE) == committed
            restarted_store = ServiceRoleStore(config=PostgresStateStoreConfig(dsn=database))
            try:
                with pytest.raises(
                    ValueError, match="checkpoint .* digest mismatch; repair required"
                ):
                    await _agent(restarted_store).rehydrate()
                store.fail_manifest = False
                await agent._persist_state()
                repaired = _agent(restarted_store)
                assert await repaired.rehydrate() == 1
                assert _snapshot(repaired) == _snapshot(agent)
            finally:
                await restarted_store.aclose()
        finally:
            await store.aclose()


class ManifestCountingStore(ServiceRoleStore):
    root_writes = 0
    root_bytes = 0
    max_root_bytes = 0
    bucket_writes = 0
    bucket_bytes = 0

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        await super().write_state(key, value)
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
        if key == STATE:
            self.root_writes += 1
            self.root_bytes += size
            self.max_root_bytes = max(self.max_root_bytes, size)
        elif key.startswith(BUCKET_PREFIX):
            self.bucket_writes += 1
            self.bucket_bytes += size


async def test_service_role_2048_flat_vs_hash_bucket_checkpoint_physical_bytes() -> None:
    results: dict[str, Any] = {}
    snapshots: dict[str, Any] = {}
    for name, agent_type in (("flat", FlatManifestHeimdall), ("buckets", Heimdall)):
        async with _measurement_database() as database:
            store = ManifestCountingStore(config=PostgresStateStoreConfig(dsn=database))
            try:
                agent = _agent(store, agent_type=agent_type)
                seed_subjects(agent, 2_048)
                await agent._persist_state()
                initial = await _allocated_bytes(store)
                store.writes = store.root_writes = store.root_bytes = 0
                store.bucket_writes = store.bucket_bytes = store.max_root_bytes = 0
                for index in range(128):
                    await agent.on_typed_message(
                        "object.event", _event(3_000 + index, subject=1_024, seconds=index % 20 + 1)
                    )
                duplicate = _event(3_127, subject=1_024, seconds=127 % 20 + 1)
                writes = store.writes
                for _ in range(1_000):
                    await agent.on_typed_message("object.event", duplicate)
                assert store.writes == writes
                await agent.on_typed_message("object.event", _event(9_000, subject=9_000))
                snapshots[name] = _snapshot(agent)
                final = await _allocated_bytes(store)
                results[name] = {
                    "writes": store.writes,
                    "root_writes": store.root_writes,
                    "root_bytes": store.root_bytes,
                    "max_root_bytes": store.max_root_bytes,
                    "bucket_writes": store.bucket_writes,
                    "bucket_bytes": store.bucket_bytes,
                    "allocated": final,
                    "steady_growth": {
                        key: final[key] - initial[key]
                        for key in ("heap_bytes", "index_bytes", "toast_bytes", "total_bytes")
                    },
                }
                restarted = _agent(store)
                assert await restarted.rehydrate() == 2_048
                assert _snapshot(restarted) == snapshots[name]
                assert list(restarted._recent_events) == list(agent._recent_events)
                if name == "flat":
                    # Measure before migration, then verify the retained live-format upgrade.
                    await restarted._persist_state()
                    migrated = _agent(store)
                    assert await migrated.rehydrate() == 2_048
                    assert _snapshot(migrated) == snapshots[name]
                    assert list(migrated._recent_events) == list(agent._recent_events)
            finally:
                await store.aclose()
    assert snapshots["flat"] == snapshots["buckets"]
    assert results["buckets"]["max_root_bytes"] < 4_500
    assert (
        results["buckets"]["root_bytes"] + results["buckets"]["bucket_bytes"]
        < results["flat"]["root_bytes"]
    )
    results["scope"] = (
        "2048 active, 128 middle updates, 1000 duplicates, eviction; no WAL attribution"
    )
    print(json.dumps(results, sort_keys=True))
