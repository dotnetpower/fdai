"""Live local-PostgreSQL checks for the T2 cache lifecycle."""

from __future__ import annotations

import asyncio
import os
import runpy
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
from psycopg.conninfo import conninfo_to_dict

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[4]


class _ValidationDsn(str):
    def __repr__(self) -> str:
        return "<isolated validation database>"


def _requires_live_db() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    dsn = value.replace("postgresql+psycopg://", "postgresql://", 1)
    target = conninfo_to_dict(dsn)
    if (
        target.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or str(target.get("port", "5432")) != "5433"
    ):
        pytest.fail("T2 cache integration requires isolated loopback PostgreSQL port 5433")
    return _ValidationDsn(dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://example@example.invalid:5433/fdai",
        "postgresql://example@127.0.0.1:5432/fdai",
        "postgresql://example@localhost/fdai",
    ],
)
def test_destructive_cache_fixture_rejects_nonvalidation_targets(
    dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_DATABASE_URL", dsn)
    with pytest.raises(pytest.fail.Exception, match="isolated loopback"):
        _requires_live_db()


def _upgrade() -> None:
    """Use Core's coordinator on a validation database with its baseline already adopted."""
    for command in (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [
            sys.executable,
            "service-migrations/migrate.py",
            "core-control-plane",
            "upgrade",
            "head",
        ],
    ):
        result = subprocess.run(  # noqa: S603 - controlled module invocation
            command,
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
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


async def test_promotion_rejects_a_partition_name_prefix_collision(database_url: str) -> None:
    store = _store(database_url)
    prefix = "a" * 24
    first = f"sha256:{prefix}{'1' * 40}"
    colliding = f"sha256:{prefix}{'2' * 40}"
    await store.promote(catalog_version=first, idempotency_key="promote-prefix-one")

    with pytest.raises(T2CacheLifecycleError, match="partition name collides"):
        await store.promote(
            catalog_version=colliding,
            idempotency_key="promote-prefix-two",
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
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """
            INSERT INTO t2_cache (catalog_version, input_hash, output, model, expires_at)
            VALUES (%s, %s, '{}'::jsonb, 'reasoner', NOW() - INTERVAL '1 hour')
            """,
            (versions[3], _digest("a")),
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
        cursor = await connection.execute("SELECT count(*) FROM t2_cache")
        assert await cursor.fetchone() == (1,)


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
    catalog_version = _digest("1")
    await _store(database_url).promote(
        catalog_version=catalog_version,
        idempotency_key="latency-promote",
    )
    store = _store(database_url, timeout_ms=250)
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


async def test_concurrent_puts_keep_one_expiry_winner_across_models(database_url: str) -> None:
    store = _store(database_url)
    active, input_hash = _digest("1"), _digest("a")
    await store.promote(catalog_version=active, idempotency_key="upsert-promote")
    now = datetime.now(UTC)
    await asyncio.gather(
        *(
            store.put(
                catalog_version=active,
                input_hash=input_hash,
                output={"winner": index},
                model=f"reasoner-{index}",
                expires_at=now + timedelta(hours=1, seconds=index),
            )
            for index in range(12)
        )
    )
    await store.put(
        catalog_version=active,
        input_hash=input_hash,
        output={"winner": "shorter"},
        model="shorter-model",
        expires_at=now + timedelta(minutes=1),
    )
    hit = await store.get(catalog_version=active, input_hash=input_hash, observed_at=now)
    assert hit is not None
    assert hit.output == {"winner": 11}
    assert hit.model == "reasoner-11"
    assert hit.expires_at == now + timedelta(hours=1, seconds=11)
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute("SELECT count(*) FROM t2_cache")
        assert await cursor.fetchone() == (1,)
    await store.promote(catalog_version=_digest("2"), idempotency_key="upsert-new-catalog")
    await store.put(
        catalog_version=_digest("2"),
        input_hash=input_hash,
        output={"winner": "new-catalog"},
        model="new-catalog-model",
        expires_at=now + timedelta(hours=2),
    )
    await store.rollback(idempotency_key="upsert-rollback")
    restored = await store.get(catalog_version=active, input_hash=input_hash)
    assert restored is not None and restored.output == {"winner": 11}


@pytest.mark.parametrize("with_rollback", [False, True])
async def test_rotation_reclaims_protected_expiry_in_batches_and_preserves_legacy(
    database_url: str,
    with_rollback: bool,
) -> None:
    store = _store(database_url)
    active = _digest("2")
    rollback = _digest("1") if with_rollback else None
    if rollback is not None:
        await store.promote(catalog_version=rollback, idempotency_key="cleanup-promote-one")
    await store.promote(catalog_version=active, idempotency_key="cleanup-promote-two")
    versions = (active,) if rollback is None else (active, rollback)
    state = await store.state()
    now = datetime.now(UTC)
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        for version in versions:
            await connection.execute(
                """
                INSERT INTO t2_cache (catalog_version, input_hash, output, model, expires_at)
                SELECT %s, 'sha256:' || lpad(to_hex(item), 64, '0'),
                       '{}'::jsonb, 'reasoner', %s
                  FROM generate_series(1, %s) AS item
                """,
                (version, now - timedelta(hours=1), 1200 // len(versions)),
            )
            await connection.execute(
                """
                INSERT INTO t2_cache (catalog_version, input_hash, output, model, expires_at)
                VALUES (%s, %s, '{"retained":true}'::jsonb, 'reasoner', %s)
                """,
                (version, _digest("f"), now + timedelta(hours=1)),
            )
        await connection.execute(
            """
            INSERT INTO t2_cache_legacy_default (
                catalog_version, input_hash, output, model, expires_at
            )
            VALUES (%s, %s, '{}'::jsonb, 'legacy', %s)
            """,
            (rollback or active, _digest("a"), now - timedelta(hours=1)),
        )

    async def rotate(key: str) -> Any:
        return await store.rotate(
            active_catalog_version=active,
            rollback_catalog_version=rollback,
            cutoff=now + timedelta(days=1),
            idempotency_key=key,
        )

    receipt = await rotate("cleanup-one")
    assert receipt.rollback_catalog_version == rollback
    assert receipt.expired_rows_deleted == 1000
    assert receipt.dropped_catalog_versions == ()
    assert receipt.cleanup_cutoff is not None
    assert now <= receipt.cleanup_cutoff < now + timedelta(hours=1)
    assert await rotate("cleanup-one") == receipt
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute("SELECT count(*) FROM t2_cache")
        assert await cursor.fetchone() == (200 + len(versions),)
    second = await rotate("cleanup-two")
    assert second.expired_rows_deleted == 200
    assert second.dropped_catalog_versions == ()
    assert await store.state() == state
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        for table, count in (
            ("t2_cache", len(versions)),
            ("t2_cache_partition_registry", len(versions)),
            ("t2_cache_catalog_transition", len(versions)),
            ("t2_cache_rotation_receipt", 2),
            ("t2_cache_legacy_default", 1),
        ):
            cursor = await connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            )
            assert await cursor.fetchone() == (count,)
    assert await store.get(catalog_version=active, input_hash=_digest("f")) is not None
    if rollback is not None:
        await store.rollback(idempotency_key="cleanup-rollback")
        assert await store.get(catalog_version=rollback, input_hash=_digest("f")) is not None


async def test_expiry_helper_runs_with_runtime_role_without_child_select_grants(
    database_url: str,
) -> None:
    store = _store(database_url)
    await store.promote(catalog_version=_digest("1"), idempotency_key="role-promote-one")
    await store.promote(catalog_version=_digest("2"), idempotency_key="role-promote-two")
    async with await store._connect() as connection:
        cursor = await connection.execute(
            """
            SELECT has_function_privilege(
                'fdai_core', 'fdai_t2_cache_prune_expired(timestamptz,integer)', 'EXECUTE'
            ) AS executable, NOT EXISTS (
                SELECT 1 FROM pg_proc, LATERAL aclexplode(proacl) AS permission
                 WHERE oid = 'fdai_t2_cache_prune_expired(timestamptz,integer)'::regprocedure
                   AND permission.grantee = 0
                   AND permission.privilege_type = 'EXECUTE'
            ) AS private
            """
        )
        assert await cursor.fetchone() == {"executable": True, "private": True}
        await connection.execute("SET LOCAL ROLE fdai_core")
        cursor = await connection.execute(
            "SELECT fdai_t2_cache_prune_expired(NOW(), 1000) AS deleted"
        )
        assert await cursor.fetchone() == {"deleted": 0}
        assert await store._partition_is_expired(
            connection, "t2_cache_p_" + "1" * 24, datetime.now(UTC)
        )
        await store._rotation_candidates(
            connection,
            active_catalog_version=_digest("2"),
            rollback_catalog_version=_digest("1"),
            cutoff=datetime.now(UTC),
        )


async def test_runtime_role_upsert_preserves_identity_and_immutable_receipts(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(database_url)
    owner_connect = store._connect

    async def connect_as_core() -> psycopg.AsyncConnection[dict[str, Any]]:
        connection = await owner_connect()
        await connection.execute("SET ROLE fdai_core")
        return connection

    monkeypatch.setattr(store, "_connect", connect_as_core)
    version, next_version, input_hash = _digest("1"), _digest("2"), _digest("a")
    promoted = await store.promote(catalog_version=version, idempotency_key="role-cache-promote")
    expiry = datetime.now(UTC) + timedelta(hours=1)
    await store.put(
        catalog_version=version,
        input_hash=input_hash,
        output={"winner": "original"},
        model="original-model",
        expires_at=expiry,
    )

    async def row() -> dict[str, Any]:
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM t2_cache WHERE catalog_version = %s AND input_hash = %s",
                (version, input_hash),
            )
            result = await cursor.fetchone()
            assert result is not None
            return result

    original = await row()
    await store.put(
        catalog_version=version,
        input_hash=input_hash,
        output={"winner": "shorter"},
        model="shorter-model",
        expires_at=expiry - timedelta(minutes=10),
    )
    assert await row() == original
    await store.put(
        catalog_version=version,
        input_hash=input_hash,
        output={"winner": "longer"},
        model="longer-model",
        expires_at=expiry + timedelta(hours=1),
    )
    updated = await row()
    for field in ("id", "catalog_version", "input_hash"):
        assert updated[field] == original[field]
    assert updated["output"] == {"winner": "longer"}
    assert updated["model"] == "longer-model"
    assert updated["created_at"] >= original["created_at"]
    assert updated["expires_at"] == expiry + timedelta(hours=1)
    await store.promote(catalog_version=next_version, idempotency_key="role-cache-promote-next")
    await store.rollback(idempotency_key="role-cache-rollback")
    hit = await store.get(catalog_version=version, input_hash=input_hash)
    assert hit is not None and hit.output == updated["output"]
    receipt = await store.rotate(
        active_catalog_version=version,
        rollback_catalog_version=next_version,
        idempotency_key="role-cache-rotate",
        cutoff=datetime.now(UTC),
    )
    assert receipt.expired_rows_deleted == 0
    assert (
        await store.promote(catalog_version=version, idempotency_key="role-cache-promote")
        == promoted
    )
    async with await store._connect() as connection:
        cursor = await connection.execute(
            """
            SELECT current_user AS actor,
                   has_table_privilege('public.t2_cache', 'UPDATE') AS cache_update,
                   has_table_privilege(%s, 'SELECT') AS child_select
            """,
            ("public.t2_cache_p_" + "1" * 24,),
        )
        assert await cursor.fetchone() == {
            "actor": "fdai_core",
            "cache_update": True,
            "child_select": False,
        }
        for table in ("t2_cache_catalog_transition", "t2_cache_rotation_receipt"):
            for operation in ("UPDATE", "DELETE"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        statement = (
                            sql.SQL("UPDATE {} SET receipt_digest = receipt_digest")
                            if operation == "UPDATE"
                            else sql.SQL("DELETE FROM {}")
                        )
                        await connection.execute(statement.format(sql.Identifier(table)))
    assert await row() == updated


@pytest.mark.parametrize(
    ("cutoff", "row_limit", "message"),
    [
        ("2026-10-30T00:00:00Z", 0, "row limit"),
        ("2026-10-30T00:00:00Z", 1001, "row limit"),
        ("2026-10-30T00:00:00Z", None, "row limit"),
        (None, 1, "finite cutoff"),
        ("infinity", 1, "finite cutoff"),
    ],
)
async def test_expiry_helper_rejects_unbounded_inputs(
    database_url: str, cutoff: str | None, row_limit: int | None, message: str
) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match=message):
            await connection.execute(
                "SELECT fdai_t2_cache_prune_expired(%s, %s)", (cutoff, row_limit)
            )
        await connection.rollback()


@pytest.mark.parametrize("duplicate_rows", [2, 10001])
async def test_migration_keeps_read_winner_or_fails_atomically_at_repair_limit(
    database_url: str, monkeypatch: pytest.MonkeyPatch, duplicate_rows: int
) -> None:
    store = _store(database_url)
    version = _digest("1")
    await store.promote(catalog_version=version, idempotency_key="repair-promote")
    migration = runpy.run_path(
        str(
            _ROOT
            / "service-migrations/branches/core-control-plane/versions"
            / "20261030_core_cache_storage_efficiency.py"
        )
    )
    statements: list[str] = []
    monkeypatch.setattr(migration["op"], "execute", statements.append)
    migration["upgrade"]()
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        try:
            await connection.execute(
                """
                ALTER TABLE t2_cache DROP CONSTRAINT t2_cache_effective_key;
                DROP INDEX idx_t2_cache_expiry_cleanup;
                DROP FUNCTION fdai_t2_cache_prune_expired(TIMESTAMPTZ, INTEGER);
                """
            )
            await connection.execute(
                """
                INSERT INTO t2_cache (
                    catalog_version, input_hash, output, model, expires_at, created_at
                )
                SELECT %s, %s, jsonb_build_object('item', item), 'reasoner',
                       NOW() + item * INTERVAL '1 second', NOW()
                  FROM generate_series(1, %s) AS item
                """,
                (version, _digest("a"), duplicate_rows + 1),
            )
            if duplicate_rows > 10000:
                with pytest.raises(
                    psycopg.errors.RaiseException, match="bounded owner maintenance"
                ):
                    async with connection.transaction():
                        await connection.execute(statements[0])
                cursor = await connection.execute("SELECT count(*) FROM t2_cache")
                assert await cursor.fetchone() == (duplicate_rows + 1,)
            else:
                await connection.execute(statements[0])
                cursor = await connection.execute("SELECT output FROM t2_cache")
                assert await cursor.fetchall() == [({"item": duplicate_rows + 1},)]
        finally:
            await connection.rollback()
