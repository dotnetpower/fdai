"""Unit tests for PostgresAdvisoryResourceLock + the ResourceLock seam.

The lock/unlock SQL flow is exercised against a fake psycopg connection
so the adapter has coverage without a live database; the in-memory and
Postgres implementations are both asserted to satisfy the ResourceLock
Protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest

from fdai.core.executor.lock import ResourceLockManager
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.shared.providers.resource_lock import ResourceLock


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def test_in_memory_manager_satisfies_protocol() -> None:
    assert isinstance(ResourceLockManager(), ResourceLock)


def test_postgres_lock_satisfies_protocol() -> None:
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://x")
    )
    assert isinstance(lock, ResourceLock)


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(dsn="")
        )


def test_config_rejects_negative_timeout() -> None:
    with pytest.raises(ValueError, match="lock_timeout_ms"):
        PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn="postgresql://x", lock_timeout_ms=-1
            )
        )


def test_acquire_issues_lock_and_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    conns: list[_FakeConn] = []

    async def _connect(_dsn: str, autocommit: bool = False) -> _FakeConn:
        conn = _FakeConn()
        conns.append(conn)
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn="postgresql://x", lock_timeout_ms=5000
        )
    )

    async def _use() -> None:
        async with lock.acquire("vm-1"):
            pass

    asyncio.run(_use())

    assert len(conns) == 1
    sqls = [c[0] for c in conns[0].calls]
    assert any("set_config" in s for s in sqls)  # lock_timeout bounded
    assert any("pg_advisory_lock" in s for s in sqls)
    assert any("pg_advisory_unlock" in s for s in sqls)
    lock_call = next(c for c in conns[0].calls if "pg_advisory_lock" in c[0])
    assert lock_call[1] == ("vm-1",)


def test_acquire_skips_timeout_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    conns: list[_FakeConn] = []

    async def _connect(_dsn: str, autocommit: bool = False) -> _FakeConn:
        conn = _FakeConn()
        conns.append(conn)
        return conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn="postgresql://x", lock_timeout_ms=0
        )
    )

    async def _use() -> None:
        async with lock.acquire("vm-2"):
            pass

    asyncio.run(_use())
    sqls = [c[0] for c in conns[0].calls]
    assert not any("set_config" in s for s in sqls)  # no timeout -> wait forever
