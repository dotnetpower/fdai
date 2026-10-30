"""Offline checks for cache-key identity and bounded rotation orchestration."""

from __future__ import annotations

import asyncio
import importlib.util
import runpy
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.delivery.persistence import postgres_t2_cache as cache

_ACTIVE = f"sha256:{'a' * 64}"
_ROLLBACK = f"sha256:{'b' * 64}"
_INPUT = f"sha256:{'c' * 64}"
_NOW = datetime(2026, 10, 30, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[4]


class _Connection:
    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self.execute = AsyncMock(
            side_effect=[SimpleNamespace(fetchone=AsyncMock(return_value=row)) for row in rows]
        )
        self.failures: list[object] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, kind: object, *_: object) -> None:
        self.failures.append(kind)

    def transaction(self) -> _Connection:
        return self


def _store(monkeypatch: pytest.MonkeyPatch, connection: _Connection) -> cache.PostgresT2Cache:
    store = cache.PostgresT2Cache(
        config=cache.PostgresT2CacheConfig(dsn="postgresql://example.com/fdai")
    )
    monkeypatch.setattr(store, "_connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(store, "_prepare_transaction", AsyncMock())
    monkeypatch.setattr(
        store, "_state", AsyncMock(return_value=cache.T2CacheCatalogState(_ACTIVE, _ROLLBACK, 2))
    )
    return store


def _receipt(**extra: object) -> dict[str, Any]:
    return {
        "idempotency_key": "rotation-one",
        "active_catalog_version": _ACTIVE,
        "rollback_catalog_version": _ROLLBACK,
        "cutoff": _NOW,
        "dropped_catalog_versions": [],
        "receipt_digest": f"sha256:{'d' * 64}",
        "recorded_at": _NOW,
        **extra,
    }


def _rotation(monkeypatch: pytest.MonkeyPatch, connection: _Connection) -> cache.PostgresT2Cache:
    store = _store(monkeypatch, connection)
    monkeypatch.setattr(store, "_rotation_receipt", AsyncMock(return_value=None))
    monkeypatch.setattr(store, "_rotation_candidates", AsyncMock(return_value=()))
    monkeypatch.setattr(store, "_insert_rotation_receipt", AsyncMock())
    return store


async def _rotate(
    store: cache.PostgresT2Cache,
    *,
    cutoff: datetime = _NOW,
    rollback: str | None = _ROLLBACK,
) -> Any:
    return await store.rotate(
        active_catalog_version=_ACTIVE,
        rollback_catalog_version=rollback,
        idempotency_key="rotation-one",
        cutoff=cutoff,
    )


async def test_put_uses_the_exact_read_key_and_preserves_expiry_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([None])
    store = _store(monkeypatch, connection)
    expiry = datetime.now(UTC) + timedelta(hours=1)
    await store.put(
        catalog_version=_ACTIVE,
        input_hash=_INPUT,
        output={"decision": "held"},
        model="another-model",
        expires_at=expiry,
    )
    query, params = connection.execute.call_args.args
    normalized = " ".join(query.split())
    assert "ON CONFLICT (catalog_version, input_hash) DO UPDATE" in normalized
    assert "(EXCLUDED.expires_at, EXCLUDED.created_at) >=" in normalized
    assert "(t2_cache.expires_at, t2_cache.created_at)" in normalized
    assert "model = EXCLUDED.model" in normalized
    updated_fields = normalized.split("DO UPDATE SET ", 1)[1].split(" WHERE ", 1)[0]
    assert updated_fields == (
        "output = EXCLUDED.output, model = EXCLUDED.model, "
        "created_at = EXCLUDED.created_at, expires_at = EXCLUDED.expires_at"
    )
    assert params[:2] == (_ACTIVE, _INPUT)
    assert params[-2:] == ("another-model", expiry)
    store._prepare_transaction.assert_awaited_once_with(connection)


async def test_put_rejects_nonactive_catalog_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([])
    store = _store(monkeypatch, connection)
    with pytest.raises(cache.T2CacheLifecycleError, match="active catalog"):
        await store.put(
            catalog_version=_ROLLBACK,
            input_hash=_INPUT,
            output={},
            model="reasoner",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    connection.execute.assert_not_awaited()


@pytest.mark.parametrize("deleted_rows", [0, 1, 1000])
async def test_rotation_cleans_expiry_and_records_the_clamped_cutoff(
    monkeypatch: pytest.MonkeyPatch, deleted_rows: int
) -> None:
    connection = _Connection([{"cleanup_cutoff": _NOW}, {"deleted_rows": deleted_rows}])
    store = _rotation(monkeypatch, connection)
    future = _NOW + timedelta(days=1)
    await _rotate(store, cutoff=future)
    first, second = connection.execute.call_args_list
    assert "LEAST(%s, statement_timestamp())" in first.args[0]
    assert first.args[1] == (future,)
    assert second.args == (
        "SELECT fdai_t2_cache_prune_expired(%s, %s) AS deleted_rows",
        (_NOW, 1000),
    )
    recorded = store._insert_rotation_receipt.call_args.kwargs
    assert recorded["expired_rows_deleted"] == deleted_rows
    assert recorded["cleanup_cutoff"] == _NOW
    assert recorded["cutoff"] == future


@pytest.mark.parametrize("deleted", [None, {"deleted_rows": -1}, {"deleted_rows": 1001}])
async def test_rotation_aborts_without_receipt_on_invalid_cleanup_result(
    monkeypatch: pytest.MonkeyPatch, deleted: dict[str, int] | None
) -> None:
    connection = _Connection([{"cleanup_cutoff": _NOW}, deleted])
    store = _rotation(monkeypatch, connection)
    with pytest.raises(cache.T2CacheLifecycleError, match="row count|row budget"):
        await _rotate(store)
    store._insert_rotation_receipt.assert_not_awaited()
    store._rotation_candidates.assert_not_awaited()
    assert connection.failures == [cache.T2CacheLifecycleError] * 2


async def test_rotation_duplicate_does_not_run_cleanup_or_rewrite_old_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([])
    store = _rotation(monkeypatch, connection)
    receipt = cache._rotation_receipt(_receipt())
    store._rotation_receipt.return_value = receipt
    assert await _rotate(store) == receipt
    assert receipt.expired_rows_deleted == 0
    assert receipt.cleanup_cutoff is None
    assert receipt.receipt_digest == _receipt()["receipt_digest"]
    connection.execute.assert_not_awaited()
    store._insert_rotation_receipt.assert_not_awaited()


async def test_rotation_stale_bindings_fail_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([])
    store = _rotation(monkeypatch, connection)
    store._state.return_value = cache.T2CacheCatalogState(_ROLLBACK, _ACTIVE, 3)
    with pytest.raises(cache.T2CacheLifecycleError, match="authoritative"):
        await _rotate(store)
    connection.execute.assert_not_awaited()


async def test_rotation_has_a_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection([])
    store = _rotation(monkeypatch, connection)
    monkeypatch.setattr(cache, "_ROTATION_TIMEOUT_S", 0.01)

    async def stalled(_: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(store, "_prepare_transaction", stalled)
    with pytest.raises(TimeoutError):
        await _rotate(store)
    store._insert_rotation_receipt.assert_not_awaited()
    assert connection.failures == [asyncio.CancelledError] * 2


@pytest.mark.parametrize("rollback", [_ROLLBACK, None])
async def test_candidates_bound_drops_without_starving_behind_live_partitions(
    rollback: str | None,
) -> None:
    connection = _Connection([])
    connection.execute = AsyncMock(
        return_value=SimpleNamespace(fetchall=AsyncMock(return_value=[]))
    )
    store = cache.PostgresT2Cache(
        config=cache.PostgresT2CacheConfig(dsn="postgresql://example.com/fdai")
    )
    assert (
        await store._rotation_candidates(
            connection,
            active_catalog_version=_ACTIVE,
            rollback_catalog_version=rollback,
            cutoff=_NOW,
        )
        == ()
    )
    query, params = connection.execute.call_args.args
    assert "NOT EXISTS" in query
    assert "cache.expires_at > %s" in query
    assert "LIMIT %s" in query
    assert "registry.catalog_version IS DISTINCT FROM %s" in query
    assert params == (_ACTIVE, rollback, _NOW, 32)


async def test_expiry_check_uses_parent_privileges_not_child_table_selects() -> None:
    connection = _Connection([{"eligible": True}])
    store = cache.PostgresT2Cache(
        config=cache.PostgresT2CacheConfig(dsn="postgresql://example.com/fdai")
    )
    partition = "t2_cache_p_" + "a" * 24
    assert await store._partition_is_expired(connection, partition, _NOW)
    query, params = connection.execute.call_args.args
    assert "SELECT 1 FROM t2_cache" in query
    assert partition not in query
    assert params == (partition, _NOW)


@pytest.mark.parametrize("rollback", [_ROLLBACK, None])
async def test_cleanup_counts_and_cutoff_are_digest_bound(rollback: str | None) -> None:
    connection = _Connection(
        [
            _receipt(
                rollback_catalog_version=rollback,
                expired_rows_deleted=7,
                cleanup_cutoff=_NOW - timedelta(seconds=1),
            )
        ]
    )
    store = cache.PostgresT2Cache(
        config=cache.PostgresT2CacheConfig(dsn="postgresql://example.com/fdai")
    )
    receipt = await store._insert_rotation_receipt(
        connection,
        idempotency_key="rotation-one",
        active_catalog_version=_ACTIVE,
        rollback_catalog_version=rollback,
        cutoff=_NOW,
        dropped_catalog_versions=(),
        expired_rows_deleted=7,
        cleanup_cutoff=_NOW - timedelta(seconds=1),
    )
    _, params = connection.execute.call_args.args
    assert params[5] == cache._canonical_digest(
        {
            "idempotency_key": "rotation-one",
            "active_catalog_version": _ACTIVE,
            "rollback_catalog_version": rollback,
            "cutoff": _NOW.isoformat(),
            "dropped_catalog_versions": (),
            "expired_rows_deleted": 7,
            "cleanup_cutoff": (_NOW - timedelta(seconds=1)).isoformat(),
        }
    )
    assert receipt.expired_rows_deleted == 7
    assert receipt.rollback_catalog_version == rollback
    assert params[2] == rollback
    assert receipt.cleanup_cutoff == _NOW - timedelta(seconds=1)


def test_migration_bounds_repair_and_privilege_without_retiring_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        _ROOT
        / "service-migrations/branches/core-control-plane/versions"
        / "20261030_core_cache_storage_efficiency.py"
    )
    spec = importlib.util.spec_from_file_location("cache_storage_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    upgrade = "\n".join(statements)
    assert migration.revision == "core_cache_storage_efficiency_20261030"
    assert migration.down_revision == "core_inventory_snapshot_membership_20261029"
    assert "UNIQUE (catalog_version, input_hash)" in upgrade
    assert "ORDER BY expires_at DESC, created_at DESC, id DESC" in upgrade
    assert "LIMIT 10001" in upgrade and "removed_rows > 10000" in upgrade
    assert "statement_timeout = '15s'" in upgrade
    assert "SECURITY DEFINER" in upgrade and "search_path = pg_catalog, public" in upgrade
    assert "LIMIT requested_row_limit" in upgrade and "requested_row_limit > 1000" in upgrade
    assert "LEAST(requested_cutoff, statement_timestamp())" in upgrade
    assert "cache.catalog_version = expired.catalog_version" in upgrade
    assert "cache.id = expired.id" in upgrade
    assert "FOR UPDATE SKIP LOCKED" in upgrade
    assert "FROM PUBLIC" in upgrade and "GRANT EXECUTE ON FUNCTION" in upgrade
    assert "GRANT DELETE" not in upgrade
    assert "t2_cache_legacy_default" not in upgrade
    assert "ALTER COLUMN rollback_catalog_version DROP NOT NULL" in upgrade
    statements.clear()
    migration.downgrade()
    downgrade = "\n".join(statements)
    assert "DROP CONSTRAINT t2_cache_effective_key" in downgrade
    assert "DROP COLUMN" not in downgrade
    assert "SET NOT NULL" not in downgrade
    assert "t2_cache_legacy_default" not in downgrade


@pytest.mark.parametrize("failure_index", [None, 0, 1])
def test_db_fixture_upgrade_uses_the_version_capacity_coordinator(
    monkeypatch: pytest.MonkeyPatch, failure_index: int | None
) -> None:
    fixture = runpy.run_path(
        str(_ROOT / "services/core-control-plane/tests/persistence/test_postgres_t2_cache.py")
    )
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert kwargs == {
            "cwd": _ROOT,
            "capture_output": True,
            "text": True,
            "check": False,
            "timeout": 120,
        }
        commands.append(command)
        failed = failure_index == len(commands) - 1
        return SimpleNamespace(returncode=int(failed), stderr="migration failed" if failed else "")

    monkeypatch.setattr(subprocess, "run", run)
    if failure_index is None:
        fixture["_upgrade"]()
    else:
        with pytest.raises(AssertionError, match="migration failed"):
            fixture["_upgrade"]()
    expected = [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [
            sys.executable,
            "service-migrations/migrate.py",
            "core-control-plane",
            "upgrade",
            "head",
        ],
    ]
    assert commands == expected[: 2 if failure_index is None else failure_index + 1]


def test_runtime_grants_separate_mutable_cache_from_append_only_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _ROOT / "service-migrations/branches/core-control-plane/versions"
    captured: dict[str, str] = {}
    for name in ("20260809_core_runtime_role.py", "20260831_core_t2_cache_lifecycle.py"):
        module = runpy.run_path(str(root / name))
        statements: list[str] = []
        monkeypatch.setattr(module["op"], "execute", statements.append)
        module["upgrade"]()
        captured[name] = " ".join("\n".join(statements).split())
    grant = captured["20260809_core_runtime_role.py"].split(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ", 1
    )[1]
    tables = {table.strip() for table in grant.split(" TO fdai_core;", 1)[0].split(",")}
    assert "t2_cache" in tables
    lifecycle = captured["20260831_core_t2_cache_lifecycle.py"]
    assert (
        "GRANT SELECT, INSERT ON TABLE "
        "t2_cache_catalog_transition, t2_cache_rotation_receipt TO fdai_core;"
    ) in lifecycle
    assert (
        "GRANT EXECUTE ON FUNCTION fdai_t2_cache_create_partition(TEXT), "
        "fdai_t2_cache_drop_partition(TEXT) TO fdai_core;"
    ) in lifecycle


@pytest.mark.parametrize(
    ("bound", "requested"),
    [(None, None), (None, _ROLLBACK), (_ROLLBACK, None)],
)
async def test_initial_catalog_rotation_requires_exact_optional_rollback_binding(
    monkeypatch: pytest.MonkeyPatch, bound: str | None, requested: str | None
) -> None:
    connection = _Connection([{"cleanup_cutoff": _NOW}, {"deleted_rows": 3}])
    store = _rotation(monkeypatch, connection)
    store._state.return_value = cache.T2CacheCatalogState(_ACTIVE, bound, 1)
    if bound != requested:
        with pytest.raises(cache.T2CacheLifecycleError, match="authoritative"):
            await _rotate(store, rollback=requested)
        connection.execute.assert_not_awaited()
        store._insert_rotation_receipt.assert_not_awaited()
    else:
        await _rotate(store, rollback=None)
        recorded = store._insert_rotation_receipt.call_args.kwargs
        assert recorded["rollback_catalog_version"] is None
        assert recorded["expired_rows_deleted"] == 3
        assert store._rotation_candidates.call_args.kwargs["rollback_catalog_version"] is None


async def test_initial_catalog_rotation_replays_nullable_receipt_without_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([])
    store = _rotation(monkeypatch, connection)
    receipt = cache._rotation_receipt(_receipt(rollback_catalog_version=None))
    store._rotation_receipt.return_value = receipt
    assert receipt.rollback_catalog_version is None
    assert await _rotate(store, rollback=None) == receipt
    connection.execute.assert_not_awaited()
    with pytest.raises(cache.T2CacheLifecycleError, match="another rotation"):
        await _rotate(store, rollback=_ROLLBACK)
    store._insert_rotation_receipt.assert_not_awaited()
