"""Live local-PostgreSQL checks for the T2 cache lifecycle."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fdai.delivery.persistence.postgres_t2_cache import (
    PostgresT2Cache,
    PostgresT2CacheConfig,
    T2CacheLifecycleError,
)
from psycopg import sql

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[4]


def _requires_live_db() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _store(dsn: str, *, timeout_ms: int = 15_000) -> PostgresT2Cache:
    return PostgresT2Cache(
        config=PostgresT2CacheConfig(
            dsn=dsn,
            statement_timeout_ms=timeout_ms,
        )
    )


@pytest.fixture
async def database_url() -> str:
    dsn = _requires_live_db()
    _upgrade()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute(
            "SELECT partition_name FROM t2_cache_partition_registry ORDER BY partition_name"
        )
        for row in await cursor.fetchall():
            await connection.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(str(row[0]))))
        await connection.execute("TRUNCATE t2_cache_legacy_default")
        await connection.execute("TRUNCATE t2_cache_rotation_receipt")
        await connection.execute("TRUNCATE t2_cache_catalog_transition")
        await connection.execute("TRUNCATE t2_cache_catalog_state")
        await connection.execute("TRUNCATE t2_cache_partition_registry")
    return dsn


async def test_migration_detaches_default_and_adds_ttl_contract(database_url: str) -> None:
    _requires_live_db()
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute(
            """
            SELECT is_nullable
              FROM information_schema.columns
             WHERE table_name = 't2_cache'
               AND column_name = 'expires_at'
            """
        )
        assert await cursor.fetchone() == ("NO",)
        cursor = await connection.execute(
            """
            SELECT indexname
              FROM pg_indexes
             WHERE tablename = 't2_cache'
               AND indexname = 'idx_t2_cache_lookup'
            """
        )
        assert await cursor.fetchone() == ("idx_t2_cache_lookup",)
        cursor = await connection.execute(
            """
            SELECT inhrelid::regclass::text
              FROM pg_inherits
             WHERE inhparent = 't2_cache'::regclass
            """
        )
        assert "t2_cache_legacy_default" not in {row[0] for row in await cursor.fetchall()}


async def test_promotion_ttl_duplicate_and_rollback(database_url: str) -> None:
    _requires_live_db()
    store = _store(database_url)
    catalog_v1 = _digest("1")
    catalog_v2 = _digest("2")
    input_hash = _digest("a")
    now = datetime.now(UTC)

    first = await store.promote(catalog_version=catalog_v1, idempotency_key="promote-v1")
    duplicate = await store.promote(catalog_version=catalog_v1, idempotency_key="promote-v1")
    assert duplicate == first
    await store.put(
        catalog_version=catalog_v1,
        input_hash=input_hash,
        output={"decision": "held"},
        model="reasoner-v1",
        expires_at=now + timedelta(minutes=5),
    )
    assert (
        await store.get(
            catalog_version=catalog_v1,
            input_hash=input_hash,
            observed_at=now,
        )
        is not None
    )
    assert (
        await store.get(
            catalog_version=catalog_v1,
            input_hash=input_hash,
            observed_at=now + timedelta(minutes=6),
        )
        is None
    )

    promoted = await store.promote(
        catalog_version=catalog_v2,
        idempotency_key="promote-v2",
    )
    assert promoted.state.active_catalog_version == catalog_v2
    assert promoted.state.rollback_catalog_version == catalog_v1
    assert (
        await store.get(
            catalog_version=catalog_v1,
            input_hash=input_hash,
            observed_at=now,
        )
        is None
    )

    rolled_back = await store.rollback(idempotency_key="rollback-v1")
    assert rolled_back.state.active_catalog_version == catalog_v1
    assert rolled_back.state.rollback_catalog_version == catalog_v2
    assert (
        await store.get(
            catalog_version=catalog_v1,
            input_hash=input_hash,
            observed_at=now,
        )
        is not None
    )


async def test_rotation_preserves_active_and_rollback_and_is_idempotent(
    database_url: str,
) -> None:
    _requires_live_db()
    store = _store(database_url)
    versions = tuple(_digest(character) for character in ("1", "2", "3"))
    now = datetime.now(UTC)

    await store.promote(catalog_version=versions[0], idempotency_key="rotate-promote-1")
    await store.put(
        catalog_version=versions[0],
        input_hash=_digest("a"),
        output={"decision": "held"},
        model="reasoner-v1",
        expires_at=now + timedelta(minutes=1),
    )
    await store.promote(catalog_version=versions[1], idempotency_key="rotate-promote-2")
    await store.promote(catalog_version=versions[2], idempotency_key="rotate-promote-3")

    receipt = await store.rotate(
        active_catalog_version=versions[2],
        rollback_catalog_version=versions[1],
        idempotency_key="rotation-1",
        cutoff=now + timedelta(minutes=2),
    )
    duplicate = await store.rotate(
        active_catalog_version=versions[2],
        rollback_catalog_version=versions[1],
        idempotency_key="rotation-1",
        cutoff=now + timedelta(minutes=2),
    )

    assert receipt.dropped_catalog_versions == (versions[0],)
    assert duplicate == receipt
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute(
            "SELECT catalog_version FROM t2_cache_partition_registry ORDER BY catalog_version"
        )
        assert tuple(row[0] for row in await cursor.fetchall()) == tuple(sorted(versions[1:]))
        cursor = await connection.execute(
            "SELECT count(*) FROM t2_cache_rotation_receipt WHERE idempotency_key = %s",
            ("rotation-1",),
        )
        assert await cursor.fetchone() == (1,)


class _FailAfterOneDrop(PostgresT2Cache):
    def __init__(self, *, config: PostgresT2CacheConfig) -> None:
        super().__init__(config=config)
        self._drop_count = 0

    async def _drop_partition(
        self,
        connection: psycopg.AsyncConnection[Any],
        partition_name: str,
    ) -> None:
        self._drop_count += 1
        if self._drop_count == 2:
            raise RuntimeError("injected second-drop failure")
        await super()._drop_partition(connection, partition_name)


async def test_partial_rotation_failure_rolls_back_ddl_and_receipt(database_url: str) -> None:
    _requires_live_db()
    config = PostgresT2CacheConfig(dsn=database_url)
    store = _FailAfterOneDrop(config=config)
    versions = tuple(_digest(character) for character in ("1", "2", "3", "4"))
    for index, version in enumerate(versions):
        await store.promote(
            catalog_version=version,
            idempotency_key=f"failure-promote-{index}",
        )

    with pytest.raises(RuntimeError, match="injected second-drop failure"):
        await store.rotate(
            active_catalog_version=versions[3],
            rollback_catalog_version=versions[2],
            idempotency_key="rotation-fails",
            cutoff=datetime.now(UTC),
        )

    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute(
            "SELECT catalog_version FROM t2_cache_partition_registry ORDER BY catalog_version"
        )
        assert tuple(row[0] for row in await cursor.fetchall()) == tuple(sorted(versions))
        cursor = await connection.execute(
            "SELECT count(*) FROM t2_cache_rotation_receipt WHERE idempotency_key = %s",
            ("rotation-fails",),
        )
        assert await cursor.fetchone() == (0,)


async def test_concurrent_rotation_serializes_and_drops_once(database_url: str) -> None:
    _requires_live_db()
    store = _store(database_url)
    versions = tuple(_digest(character) for character in ("1", "2", "3"))
    for index, version in enumerate(versions):
        await store.promote(
            catalog_version=version,
            idempotency_key=f"concurrent-promote-{index}",
        )
    cutoff = datetime.now(UTC)

    receipts = await asyncio.gather(
        store.rotate(
            active_catalog_version=versions[2],
            rollback_catalog_version=versions[1],
            idempotency_key="concurrent-rotation-1",
            cutoff=cutoff,
        ),
        store.rotate(
            active_catalog_version=versions[2],
            rollback_catalog_version=versions[1],
            idempotency_key="concurrent-rotation-2",
            cutoff=cutoff,
        ),
    )

    assert sorted(len(receipt.dropped_catalog_versions) for receipt in receipts) == [0, 1]
    assert {version for receipt in receipts for version in receipt.dropped_catalog_versions} == {
        versions[0]
    }


def _plan_nodes(plan: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        if isinstance(child, dict):
            nodes.extend(_plan_nodes(child))
    return tuple(nodes)


async def test_indexed_hit_and_miss_complete_under_statement_timeout(
    database_url: str,
) -> None:
    _requires_live_db()
    store = _store(database_url, timeout_ms=250)
    catalog_version = _digest("1")
    await store.promote(
        catalog_version=catalog_version,
        idempotency_key="latency-promote",
    )
    observed_at = datetime.now(UTC)
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """
            INSERT INTO t2_cache (
                catalog_version, input_hash, output, model, expires_at
            )
            SELECT %s,
                   'sha256:' || lpad(to_hex(item), 64, '0'),
                   jsonb_build_object('item', item),
                   'reasoner-v1',
                   %s
              FROM generate_series(1, 5000) AS item
            """,
            (catalog_version, observed_at + timedelta(hours=1)),
        )
        await connection.execute("ANALYZE t2_cache")
        plans = []
        for input_hash in (_digest("f"), f"sha256:{42:064x}"):
            cursor = await connection.execute(
                """
                EXPLAIN (FORMAT JSON)
                SELECT cache.catalog_version, cache.input_hash, cache.output, cache.model,
                       cache.created_at, cache.expires_at
                  FROM t2_cache AS cache
                  JOIN t2_cache_catalog_state AS state
                    ON state.singleton = TRUE
                   AND state.active_catalog_version = cache.catalog_version
                 WHERE cache.catalog_version = %s
                   AND cache.input_hash = %s
                   AND cache.expires_at > %s
                 ORDER BY cache.expires_at DESC, cache.created_at DESC
                 LIMIT 1
                """,
                (catalog_version, input_hash, observed_at),
            )
            row = await cursor.fetchone()
            assert row is not None
            plans.append(row[0][0]["Plan"])

    for plan in plans:
        assert any("Index" in str(node.get("Node Type", "")) for node in _plan_nodes(plan))
    assert (
        await store.get(
            catalog_version=catalog_version,
            input_hash=f"sha256:{42:064x}",
            observed_at=observed_at,
        )
        is not None
    )
    assert (
        await store.get(
            catalog_version=catalog_version,
            input_hash=_digest("f"),
            observed_at=observed_at,
        )
        is None
    )


async def test_rotation_rejects_stale_active_or_rollback_identity(database_url: str) -> None:
    _requires_live_db()
    store = _store(database_url)
    active = _digest("1")
    rollback = _digest("2")
    await store.promote(catalog_version=rollback, idempotency_key="stale-promote-1")
    await store.promote(catalog_version=active, idempotency_key="stale-promote-2")

    with pytest.raises(T2CacheLifecycleError, match="does not match authoritative"):
        await store.rotate(
            active_catalog_version=active,
            rollback_catalog_version=_digest("3"),
            idempotency_key="stale-rotation",
            cutoff=datetime.now(UTC),
        )
