"""Unit tests for the OutboxStore in-memory + Postgres backends."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest

from fdai.delivery.persistence.postgres_outbox import (
    PostgresOutboxStore,
    PostgresOutboxStoreConfig,
)
from fdai.shared.providers.outbox import OutboxStatus, OutboxStore
from fdai.shared.providers.testing.outbox import InMemoryOutboxStore


def test_in_memory_satisfies_protocol() -> None:
    assert isinstance(InMemoryOutboxStore(), OutboxStore)


def test_in_memory_claim_lifecycle() -> None:
    store = InMemoryOutboxStore()

    async def _run() -> None:
        first = await store.claim("k")
        assert first.status is OutboxStatus.NEW
        # Re-claim before completion -> crash-suspect / concurrent attempt.
        again = await store.claim("k")
        assert again.status is OutboxStatus.IN_PROGRESS
        await store.complete("k", {"outcome": "dispatched"})
        done = await store.claim("k")
        assert done.status is OutboxStatus.DONE
        assert done.result == {"outcome": "dispatched"}

    asyncio.run(_run())


def test_in_memory_returns_defensive_copy() -> None:
    store = InMemoryOutboxStore()

    async def _run() -> None:
        await store.claim("k")
        await store.complete("k", {"nested": {"a": 1}})
        claim = await store.claim("k")
        assert claim.result is not None
        dict(claim.result)["nested"]["a"] = 999
        again = await store.claim("k")
        assert again.result == {"nested": {"a": 1}}

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
    def __init__(self, *, claim_rowcount: int, select_row: dict[str, Any] | None) -> None:
        self._claim_rowcount = claim_rowcount
        self._select_row = select_row
        self.executed: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self.executed.append((sql, params))
        stripped = sql.strip()
        if stripped.startswith("INSERT INTO action_outbox (idempotency_key, status)"):
            return _FakeCursor(self._claim_rowcount, None)
        if stripped.startswith("SELECT status"):
            return _FakeCursor(1 if self._select_row else 0, self._select_row)
        return _FakeCursor(1, None)

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _patch(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn) -> None:
    async def _connect(*_a: object, **_k: object) -> _FakeConn:
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)


def test_postgres_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresOutboxStore(config=PostgresOutboxStoreConfig(dsn=""))


def test_postgres_claim_new_on_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(claim_rowcount=1, select_row=None)
    _patch(monkeypatch, conn)
    store = PostgresOutboxStore(config=PostgresOutboxStoreConfig(dsn="postgresql://x"))
    claim = asyncio.run(store.claim("k"))
    assert claim.status is OutboxStatus.NEW


def test_postgres_claim_in_progress_on_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(claim_rowcount=0, select_row={"status": "in_progress", "result": None})
    _patch(monkeypatch, conn)
    store = PostgresOutboxStore(config=PostgresOutboxStoreConfig(dsn="postgresql://x"))
    claim = asyncio.run(store.claim("k"))
    assert claim.status is OutboxStatus.IN_PROGRESS


def test_postgres_claim_done_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(
        claim_rowcount=0,
        select_row={"status": "done", "result": {"outcome": "dispatched"}},
    )
    _patch(monkeypatch, conn)
    store = PostgresOutboxStore(config=PostgresOutboxStoreConfig(dsn="postgresql://x"))
    claim = asyncio.run(store.claim("k"))
    assert claim.status is OutboxStatus.DONE
    assert claim.result == {"outcome": "dispatched"}


def test_postgres_complete_upserts_done(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(claim_rowcount=1, select_row=None)
    _patch(monkeypatch, conn)
    store = PostgresOutboxStore(config=PostgresOutboxStoreConfig(dsn="postgresql://x"))
    asyncio.run(store.complete("k", {"outcome": "dispatched"}))
    assert any("status = 'done'" in sql for sql, _ in conn.executed)
