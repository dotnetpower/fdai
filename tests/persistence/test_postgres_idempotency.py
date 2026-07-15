"""Unit tests for the IdempotencyStore in-memory + Postgres backends."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest

from fdai.delivery.persistence.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.testing.idempotency import InMemoryIdempotencyStore


def test_in_memory_satisfies_protocol() -> None:
    assert isinstance(InMemoryIdempotencyStore(), IdempotencyStore)


def test_in_memory_record_then_seen_round_trip() -> None:
    store = InMemoryIdempotencyStore()

    async def _run() -> None:
        assert await store.seen("k") is None
        first = await store.record("k", {"outcome": "published"})
        assert first is True
        again = await store.record("k", {"outcome": "other"})
        assert again is False  # first-writer wins
        seen = await store.seen("k")
        assert seen == {"outcome": "published"}  # unchanged by the racing write

    asyncio.run(_run())


def test_in_memory_returns_defensive_copy() -> None:
    store = InMemoryIdempotencyStore()

    async def _run() -> None:
        await store.record("k", {"nested": {"a": 1}})
        got = await store.seen("k")
        assert got is not None
        got["nested"]["a"] = 999  # mutate the returned copy
        again = await store.seen("k")
        assert again == {"nested": {"a": 1}}  # store not corrupted

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Postgres backend (fake connection - no live DB)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rowcount: int, row: dict[str, Any] | None) -> None:
        self.rowcount = rowcount
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    def __init__(self, *, row: dict[str, Any] | None, rowcount: int) -> None:
        self._row = row
        self._rowcount = rowcount
        self.executed: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self.executed.append((sql, params))
        if sql.strip().startswith("SELECT result"):
            return _FakeCursor(1 if self._row else 0, self._row)
        return _FakeCursor(self._rowcount, None)

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def test_postgres_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn=""))


def test_postgres_record_returns_true_on_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(row=None, rowcount=1)

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))
    inserted = asyncio.run(store.record("k", {"outcome": "published"}))
    assert inserted is True
    assert any("ON CONFLICT" in sql for sql, _ in conn.executed)


def test_postgres_record_returns_false_on_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(row=None, rowcount=0)  # ON CONFLICT skipped -> rowcount 0

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))
    inserted = asyncio.run(store.record("k", {"outcome": "published"}))
    assert inserted is False


def test_postgres_replace_if_uses_json_compare_and_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(row=None, rowcount=1)

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))

    replaced = asyncio.run(
        store.replace_if("k", {"state": "pending"}, {"state": "completed"})
    )

    assert replaced is True
    assert any("result = %s::jsonb" in sql for sql, _ in conn.executed)


def test_postgres_remove_if_returns_false_when_expected_value_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(row=None, rowcount=0)

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))

    removed = asyncio.run(store.remove_if("k", {"state": "pending"}))

    assert removed is False
    assert any(sql.strip().startswith("DELETE") for sql, _ in conn.executed)


def test_postgres_insert_or_replace_if_is_one_atomic_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(row=None, rowcount=1)

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))

    completed = asyncio.run(
        store.insert_or_replace_if(
            "k",
            {"state": "pending"},
            {"state": "completed", "receipt_ref": "OPS-42"},
        )
    )

    assert completed is True
    mutations = [sql for sql, _ in conn.executed if "action_idempotency" in sql]
    assert len(mutations) == 2  # CREATE TABLE + one atomic completion statement
    assert "ON CONFLICT" in mutations[1]


def test_postgres_seen_returns_stored_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(row={"result": {"outcome": "published"}}, rowcount=0)

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))
    got = asyncio.run(store.seen("k"))
    assert got == {"outcome": "published"}


def test_postgres_config_rejects_bad_connect_timeout() -> None:
    # H9: connect_timeout bounds the handshake; a non-positive value is invalid.
    with pytest.raises(ValueError, match="connect_timeout_s"):
        PostgresIdempotencyStore(
            config=PostgresIdempotencyStoreConfig(dsn="postgresql://x", connect_timeout_s=0)
        )


def test_postgres_seen_fails_loud_on_non_object_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    # H8: a stored non-object result must NOT be masked as a miss (which would
    # silently re-execute a mutation); fail loud so the drift is visible.
    conn = _FakeConn(row={"result": ["not", "an", "object"]}, rowcount=0)

    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    store = PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://x"))
    with pytest.raises(ValueError, match="non-object result"):
        asyncio.run(store.seen("k"))
