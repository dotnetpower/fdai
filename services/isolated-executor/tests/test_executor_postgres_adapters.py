"""Focused tests for Executor-owned PostgreSQL adapters."""

from __future__ import annotations

import json
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
        "isolated-executor:attempt-one",
        {"revision": 1},
        {
            "kind": "isolated_executor.shadow_terminal",
            "idempotency_key": "attempt-one",
            "mode": "shadow",
        },
    )

    assert created is True
    assert connection.transaction_entries == 1
    insert_calls = [call for call in connection.calls if "INSERT INTO" in call[0]]
    assert len(insert_calls) == 2
    assert insert_calls[0][1][0] == "isolated-executor:attempt-one"
    assert "%s" in insert_calls[0][0]
    assert "isolated-executor:attempt-one" not in insert_calls[0][0]


async def test_state_store_rejects_foreign_namespace_and_audit_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    with pytest.raises(ValueError, match="namespace"):
        await store.read_state("core-control-plane:attempt-one")
    assert await store.read_state("workflow:automation-hold:" + "a" * 64) is None
    with pytest.raises(ValueError, match="namespace"):
        await store.write_state_with_audit_if_absent(
            "workflow:automation-hold:" + "a" * 64,
            {"revision": 1},
            {
                "kind": "isolated_executor.shadow_terminal",
                "idempotency_key": "attempt-one",
                "mode": "shadow",
            },
        )
    with pytest.raises(ValueError, match="intent or terminal"):
        await store.append_audit_entry({"kind": "foreign.audit", "mode": "enforce"})


@pytest.mark.parametrize(
    ("database_role", "ready"),
    (("fdai_core", True), ("fdai_executor", False)),
)
async def test_state_store_readiness_requires_exact_role_and_privileges(
    monkeypatch: pytest.MonkeyPatch,
    database_role: str,
    ready: bool,
) -> None:
    connection = _Connection(rows=[None, {"database_role": database_role, "ready": ready}])

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    with pytest.raises(RuntimeError, match="database role or persistence grants"):
        await store.assert_schema()

    readiness_sql = next(sql for sql, _params in connection.calls if "pg_roles" in sql)
    for fragment in (
        "current_user = 'fdai_executor'",
        "NOT login_role.rolsuper",
        "NOT login_role.rolcreaterole",
        "NOT login_role.rolbypassrls",
        "NOT pg_has_role(current_user, 'pg_read_all_data', 'MEMBER')",
        "NOT pg_has_role(current_user, 'pg_write_all_data', 'MEMBER')",
        "NOT has_table_privilege(current_user, 'audit_log', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'state_kv', 'TRUNCATE')",
        "NOT has_table_privilege(current_user, 'executor_receipt_outbox', 'DELETE')",
    ):
        assert fragment in readiness_sql


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
            {"database_role": "fdai_executor", "ready": True},
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


@pytest.mark.parametrize(
    ("database_role", "ready"),
    (("fdai_core", True), ("fdai_executor", False)),
)
async def test_idempotency_readiness_requires_exact_role_and_privileges(
    monkeypatch: pytest.MonkeyPatch,
    database_role: str,
    ready: bool,
) -> None:
    connection = _Connection(rows=[None, {"database_role": database_role, "ready": ready}])

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresIdempotencyStore(
        config=PostgresIdempotencyStoreConfig(dsn="postgresql://example")
    )

    with pytest.raises(RuntimeError, match="database role or idempotency grants"):
        await store.assert_schema()

    readiness_sql = next(sql for sql, _params in connection.calls if "pg_roles" in sql)
    for fragment in (
        "current_user = 'fdai_executor'",
        "NOT login_role.rolsuper",
        "NOT login_role.rolcreaterole",
        "NOT login_role.rolbypassrls",
        "NOT pg_has_role(current_user, 'pg_read_all_data', 'MEMBER')",
        "NOT pg_has_role(current_user, 'pg_write_all_data', 'MEMBER')",
        "NOT has_table_privilege(current_user, 'action_idempotency', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'action_idempotency', 'DELETE')",
    ):
        assert fragment in readiness_sql


async def test_executor_receipt_is_committed_to_outbox_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))
    receipt_id = uuid4()

    await store.commit_receipt(
        receipt_id,
        "resource:one",
        {"status": "dispatched"},
        command_id="command-one",
        command_offset=42,
    )

    inserts = [call for call in connection.calls if "INSERT INTO" in call[0]]
    assert len(inserts) == 3
    assert inserts[0][1][0] == f"isolated-executor:receipt:{receipt_id}"
    assert inserts[1][1][0] == "isolated-executor:command-receipt:command-one"
    assert json.loads(inserts[1][1][1]) == {"status": "dispatched"}
    assert inserts[2][1][0] == receipt_id
    assert inserts[2][1][1] == "resource:one"
    assert "COALESCE(executor_receipt_outbox.payload -> 'receipt'" in inserts[2][0]
    assert "executor_receipt_outbox.payload)::jsonb" in inserts[2][0]
    assert "(EXCLUDED.payload -> 'receipt')::jsonb" in inserts[2][0]
    assert json.loads(inserts[2][1][2]) == {
        "receipt": {"status": "dispatched"},
        "telemetry": {"command_id": "command-one", "command_offset": 42},
    }
    assert connection.transaction_entries == 1


async def test_executor_receipt_claim_restores_correlation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_id = uuid4()
    connection = _Connection(
        rows=[
            None,
            [
                {
                    "receipt_id": receipt_id,
                    "partition_key": "resource:one",
                    "payload": {
                        "receipt": {"status": "dispatched", "command_id": "command-one"},
                        "telemetry": {"command_id": "command-one", "command_offset": 42},
                    },
                }
            ],
        ]
    )

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    pending = await store.claim_receipts(limit=1)

    assert len(pending) == 1
    assert pending[0].receipt_id == receipt_id
    assert pending[0].payload == {"status": "dispatched", "command_id": "command-one"}
    assert pending[0].command_id == "command-one"
    assert pending[0].command_offset == 42


async def test_executor_receipt_readback_uses_command_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        rows=[
            None,
            {"value": {"status": "rejected", "command_id": "command-one"}},
        ]
    )

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    receipt = await store.read_committed_receipt("command-one")

    assert receipt == {"status": "rejected", "command_id": "command-one"}
    select_sql, params = next(
        (sql, params) for sql, params in connection.calls if "SELECT value FROM state_kv" in sql
    )
    assert "WHERE key = %s" in select_sql
    assert params == ("isolated-executor:command-receipt:command-one",)


async def test_executor_receipt_readback_backfills_legacy_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        rows=[
            None,
            None,
            {
                "payload": {
                    "receipt": {"status": "rejected", "command_id": "command-one"},
                    "telemetry": {"command_id": "command-one", "command_offset": 42},
                }
            },
        ]
    )

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    receipt = await store.read_committed_receipt("command-one")

    assert receipt == {"status": "rejected", "command_id": "command-one"}
    legacy_sql = next(sql for sql, _params in connection.calls if "ORDER BY created_at" in sql)
    assert "telemetry" in legacy_sql
    backfill = next(
        params
        for sql, params in connection.calls
        if "Executor command receipt backfill" not in sql and "INSERT INTO state_kv" in sql
    )
    assert backfill[0] == "isolated-executor:command-receipt:command-one"


def test_state_hash_chain_is_canonical_and_ordered() -> None:
    assert _canonical({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    first = _next_hash("0" * 64, {"seq": 1})
    second = _next_hash(first, {"seq": 2})
    assert first != second
    assert second != _next_hash("0" * 64, {"seq": 2})


async def test_postgres_adapters_remaining_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_executor_service.adapters.postgres_state import (
        _audit_event_id,
        _decode_receipt_outbox_record,
        _json_object,
    )

    for fn, match in [
        (lambda: PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn="")), "dsn"),
        (
            lambda: PostgresIdempotencyStore(
                config=PostgresIdempotencyStoreConfig(dsn="postgresql://x", connect_timeout_s=0)
            ),
            "connect_timeout_s",
        ),
        (
            lambda: PostgresAdvisoryResourceLock(config=PostgresAdvisoryResourceLockConfig(dsn="")),
            "dsn",
        ),
        (
            lambda: PostgresAdvisoryResourceLock(
                config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://x", connect_timeout_s=0)
            ),
            "connect_timeout_s",
        ),
        (
            lambda: PostgresStateStore(
                config=PostgresStateStoreConfig(dsn="postgresql://x", statement_timeout_ms=0)
            ),
            "statement_timeout_ms",
        ),
        (
            lambda: PostgresStateStore(
                config=PostgresStateStoreConfig(dsn="postgresql://x", connect_timeout_s=0)
            ),
            "connect_timeout_s",
        ),
    ]:
        with pytest.raises(ValueError, match=match):
            fn()  # type: ignore[no-untyped-call]

    # PostgresIdempotencyStore.seen & assert_schema happy path
    idem_conn = _Connection(
        rows=[
            None,
            None,
            None,
            {"result": {"outcome": "dispatched"}},
            None,
            {"result": "not-a-dict"},
            None,
            {"database_role": "fdai_executor", "ready": True},
            [
                {"column_name": "idempotency_key"},
                {"column_name": "result"},
                {"column_name": "recorded_at"},
            ],
            [{"attname": "idempotency_key"}],
        ]
    )

    async def connect_idem(*_args: object, **_kwargs: object) -> _Connection:
        return idem_conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect_idem)
    idem_store = PostgresIdempotencyStore(
        config=PostgresIdempotencyStoreConfig(dsn="postgresql://example")
    )
    assert await idem_store.seen("k1") is None
    assert await idem_store.seen("k2") == {"outcome": "dispatched"}
    with pytest.raises(ValueError, match="not a JSON object"):
        await idem_store.seen("k3")
    await idem_store.assert_schema()

    # PostgresAdvisoryResourceLock with lock_timeout_ms=0 and unlock failure
    class _UnlockFailConn(_Connection):
        async def execute(self, sql: str, params: Any = None) -> _Cursor:
            self.calls.append((sql, params))
            if "pg_advisory_unlock" in sql:
                raise RuntimeError("unlock failed")
            return _Cursor(None)

    unlock_conn = _UnlockFailConn()

    async def connect_lock(*_args: object, **_kwargs: object) -> _Connection:
        return unlock_conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect_lock)
    zero_lock = PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn="postgresql://example", lock_timeout_ms=0)
    )
    async with zero_lock.acquire("resource:zero"):
        pass

    # PostgresStateStore remaining branches
    state_conn = _Connection(
        rows=[
            # 1. assert_schema missing columns
            None,
            {"database_role": "fdai_executor", "ready": True},
            [{"table_name": "state_kv", "column_name": "key"}],
            [{"attname": "receipt_id"}],
            # 2. assert_schema happy path
            None,
            {"database_role": "fdai_executor", "ready": True},
            [
                {"table_name": "state_kv", "column_name": "key"},
                {"table_name": "state_kv", "column_name": "value"},
                {"table_name": "audit_log", "column_name": "seq"},
                {"table_name": "audit_log", "column_name": "event_id"},
                {"table_name": "audit_log", "column_name": "entry"},
                {"table_name": "audit_log", "column_name": "previous_hash"},
                {"table_name": "audit_log", "column_name": "entry_hash"},
                {"table_name": "executor_receipt_outbox", "column_name": "receipt_id"},
                {"table_name": "executor_receipt_outbox", "column_name": "partition_key"},
                {"table_name": "executor_receipt_outbox", "column_name": "payload"},
                {"table_name": "executor_receipt_outbox", "column_name": "created_at"},
                {"table_name": "executor_receipt_outbox", "column_name": "published_at"},
                {"table_name": "executor_receipt_outbox", "column_name": "attempt_count"},
                {"table_name": "executor_receipt_outbox", "column_name": "next_attempt_at"},
            ],
            [{"attname": "receipt_id"}],
            # 3. read_state found
            None,
            {"value": '{"a": 1}'},
            # 4. write_state_with_audit_if_absent conflict (returns False)
            None,
            None,
            # 5. read_committed_receipt miss
            None,
            None,
            None,
            # 6. read_committed_receipt legacy command_id mismatch
            None,
            None,
            {"payload": {"command_id": "other"}},
            # 7. claim_receipts empty
            None,
            [],
            # 8. mark_receipt_published
            None,
            None,
        ]
    )

    async def connect_state(*_args: object, **_kwargs: object) -> _Connection:
        return state_conn

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect_state)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn="postgresql://example"))

    with pytest.raises(RuntimeError, match="schema is missing or incompatible"):
        await store.assert_schema()
    await store.assert_schema()

    assert await store.read_state("isolated-executor:k1") == {"a": 1}
    assert (
        await store.write_state_with_audit_if_absent(
            "isolated-executor:k1",
            {"a": 1},
            {"kind": "isolated_executor.shadow_terminal", "mode": "shadow"},
        )
        is False
    )

    with pytest.raises(ValueError, match="command id MUST NOT be empty"):
        await store.read_committed_receipt("")
    assert await store.read_committed_receipt("cmd-miss") is None
    with pytest.raises(RuntimeError, match="command id mismatched"):
        await store.read_committed_receipt("cmd-1")

    with pytest.raises(ValueError, match="limit MUST be in"):
        await store.claim_receipts(limit=0)
    assert await store.claim_receipts(limit=5) == ()
    await store.mark_receipt_published(uuid4())

    with pytest.raises(ValueError, match="mode MUST be"):
        await store.append_audit_entry(
            {"kind": "isolated_executor.shadow_terminal", "mode": "invalid"}
        )

    # Rowcount conflicts in commit_receipt and legacy backfill
    state_conn.rowcount = 0
    with pytest.raises(RuntimeError, match="different terminal receipt"):
        await store.commit_receipt(uuid4(), "pk", {"a": 1}, command_id="c1", command_offset=1)

    state_conn.rows = [None, None, {"payload": {"command_id": "c1"}}]
    with pytest.raises(RuntimeError, match="backfill conflicted"):
        await store.read_committed_receipt("c1")

    # Helper functions
    assert _audit_event_id({"event_id": str(uuid4())})
    assert _audit_event_id({"event_id": "not-a-uuid", "idempotency_key": "k"})
    with pytest.raises(RuntimeError, match="not a JSON object"):
        _json_object(123, record_name="test")
    with pytest.raises(RuntimeError, match="envelope is malformed"):
        _decode_receipt_outbox_record({"receipt": "bad", "telemetry": {}})
    with pytest.raises(RuntimeError, match="command id is missing"):
        _decode_receipt_outbox_record({"receipt": {}, "telemetry": {"command_id": ""}})
    with pytest.raises(RuntimeError, match="command offset is malformed"):
        _decode_receipt_outbox_record(
            {"receipt": {}, "telemetry": {"command_id": "c1", "command_offset": True}}
        )
