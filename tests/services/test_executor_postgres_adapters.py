"""Focused tests for Executor-owned PostgreSQL adapters."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, Self
from uuid import uuid4

import psycopg
import pytest
from fdai_executor_service.adapters.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai_executor_service.adapters.postgres_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai_executor_service.adapters.postgres_state import (
    PostgresStateStore,
    PostgresStateStoreConfig,
    _canonical,
    _next_hash,
)
from fdai_service_contracts.executor import IdempotencyStore, ResourceLock


class _Cursor:
    def __init__(self, row: Any = None, *, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    async def fetchone(self) -> Any:
        return self._row

    async def fetchall(self) -> list[Any]:
        return list(self._row) if isinstance(self._row, list) else []


class _Transaction(AbstractAsyncContextManager[None]):
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> None:
        self._connection.transaction_entries += 1
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[Any] | None = None, *, rowcount: int = 1) -> None:
        self.rows = list(rows or [])
        self.rowcount = rowcount
        self.calls: list[tuple[str, Any]] = []
        self.transaction_entries = 0

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.calls.append((sql, params))
        row = self.rows.pop(0) if self.rows else None
        return _Cursor(row, rowcount=self.rowcount)

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def test_postgres_adapter_config_guards_and_protocols() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=""))
    with pytest.raises(ValueError, match="lock_timeout_ms"):
        PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn="postgresql://example",
                lock_timeout_ms=-1,
            )
        )
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        PostgresIdempotencyStore(
            config=PostgresIdempotencyStoreConfig(
                dsn="postgresql://example",
                statement_timeout_ms=0,
            )
        )
    assert isinstance(
        PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
        ),
        ResourceLock,
    )
    assert isinstance(
        PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="postgresql://example")),
        IdempotencyStore,
    )


async def test_state_claim_and_audit_share_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(rows=[None, {"key": "attempt"}, None, None, None])

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    created = await store.write_state_with_audit_if_absent(
        "attempt-one",
        {"revision": 1},
        {"idempotency_key": "attempt-one", "mode": "shadow"},
    )

    assert created is True
    assert connection.transaction_entries == 1
    insert_calls = [call for call in connection.calls if "INSERT INTO" in call[0]]
    assert len(insert_calls) == 2
    assert insert_calls[0][1][0] == "attempt-one"
    assert "%s" in insert_calls[0][0]
    assert "attempt-one" not in insert_calls[0][0]


async def test_resource_lock_uses_bound_key_and_always_unlocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example")
    )

    with pytest.raises(RuntimeError, match="effect failed"):
        async with lock.acquire("resource:one"):
            raise RuntimeError("effect failed")

    lock_calls = [call for call in connection.calls if "pg_advisory_" in call[0]]
    assert [call[1] for call in lock_calls] == [("resource:one",), ("resource:one",)]


async def test_idempotency_store_is_first_writer_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(rowcount=0)

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresIdempotencyStore(
        config=PostgresIdempotencyStoreConfig(dsn="postgresql://example")
    )

    created = await store.record("effect-one", {"outcome": "dispatched"})

    assert created is False
    mutation = next(call for call in connection.calls if "ON CONFLICT" in call[0])
    assert mutation[1][0] == "effect-one"
    assert "effect-one" not in mutation[0]
    assert not any("CREATE TABLE" in sql.upper() for sql, _params in connection.calls)


async def test_idempotency_store_fails_closed_when_schema_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        rows=[
            None,
            [{"column_name": "idempotency_key"}],
            [{"attname": "idempotency_key"}],
        ]
    )

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresIdempotencyStore(
        config=PostgresIdempotencyStoreConfig(dsn="postgresql://example")
    )

    with pytest.raises(RuntimeError, match="schema is missing or incompatible"):
        await store.assert_schema()


async def test_executor_receipt_is_committed_to_outbox_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))
    receipt_id = uuid4()

    await store.commit_receipt(receipt_id, "resource:one", {"status": "dispatched"})

    inserts = [call for call in connection.calls if "INSERT INTO" in call[0]]
    assert len(inserts) == 2
    assert inserts[0][1][0] == f"isolated-executor:receipt:{receipt_id}"
    assert inserts[1][1][0] == receipt_id
    assert inserts[1][1][1] == "resource:one"
    assert connection.transaction_entries == 1


def test_state_hash_chain_is_canonical_and_ordered() -> None:
    assert _canonical({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    first = _next_hash("0" * 64, {"seq": 1})
    second = _next_hash(first, {"seq": 2})
    assert first != second
    assert second != _next_hash("0" * 64, {"seq": 2})
