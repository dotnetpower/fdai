"""PostgreSQL durable state and hash-chained audit adapter for Executor attempts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from fdai_executor_service.ports import PendingExecutorReceipt

_GENESIS_HASH: Final[str] = "0" * 64
_AUDIT_APPEND_LOCK_KEY: Final[int] = 0x0FDA10AAAAAA01


@dataclass(frozen=True, slots=True)
class PostgresStateStoreConfig:
    """Bounded connection and statement settings for Executor persistence."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresStateStore:
    """Persist only the state and audit operations used by the Executor."""

    def __init__(self, *, config: PostgresStateStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresStateStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        """Append one audit record under the global hash-chain lock."""

        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                await self._append_audit(connection, dict(entry))

    async def assert_schema(self) -> None:
        """Fail startup unless all Executor-owned persistence contracts exist."""
        required = {
            "state_kv": {"key", "value"},
            "audit_log": {
                "seq",
                "event_id",
                "entry",
                "previous_hash",
                "entry_hash",
            },
            "executor_receipt_outbox": {
                "receipt_id",
                "partition_key",
                "payload",
                "created_at",
                "published_at",
                "attempt_count",
                "next_attempt_at",
            },
        }
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await self._set_statement_timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
                    (sorted(required),),
                )
            ).fetchall()
            outbox_primary_key = await (
                await connection.execute(
                    "SELECT a.attname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
                    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                    "WHERE n.nspname = current_schema() "
                    "AND t.relname = 'executor_receipt_outbox' AND c.contype = 'p' "
                    "ORDER BY k.ord"
                )
            ).fetchall()
        observed: dict[str, set[str]] = {table: set() for table in required}
        for row in rows:
            observed[str(row["table_name"])].add(str(row["column_name"]))
        if any(not columns <= observed[table] for table, columns in required.items()) or tuple(
            str(row["attname"]) for row in outbox_primary_key
        ) != ("receipt_id",):
            raise RuntimeError("Executor persistence schema is missing or incompatible")

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        """Read one durable attempt record without treating corruption as a miss."""

        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    (key,),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        return _json_object(row["value"], record_name="state value")

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        """Atomically claim one attempt and append its terminal audit record."""

        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                cursor = await connection.execute(
                    """
                    INSERT INTO state_kv (key, value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO NOTHING
                    RETURNING key
                    """,
                    (key, _canonical(value)),
                )
                if await cursor.fetchone() is None:
                    return False
                await self._append_audit(connection, dict(audit_entry))
        return True

    async def commit_receipt(
        self,
        receipt_id: UUID,
        partition_key: str,
        payload: Mapping[str, Any],
        *,
        command_id: str,
        command_offset: int | None,
    ) -> None:
        """Atomically commit terminal receipt state and its publication outbox."""
        async with (
            await psycopg.AsyncConnection.connect(
                self._config.dsn,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection,
            connection.transaction(),
        ):
            await self._set_statement_timeout(connection)
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO NOTHING",
                (f"isolated-executor:receipt:{receipt_id}", _canonical(payload)),
            )
            await connection.execute(
                "INSERT INTO executor_receipt_outbox (receipt_id, partition_key, payload) "
                "VALUES (%s, %s, %s::jsonb) ON CONFLICT (receipt_id) DO NOTHING",
                (
                    receipt_id,
                    partition_key,
                    _canonical(
                        _receipt_outbox_record(
                            payload,
                            command_id=command_id,
                            command_offset=command_offset,
                        )
                    ),
                ),
            )

    async def claim_receipts(self, *, limit: int) -> tuple[PendingExecutorReceipt, ...]:
        """Lease due unpublished receipts by moving their retry timestamp."""
        if limit < 1 or limit > 1000:
            raise ValueError("Executor receipt outbox limit MUST be in [1, 1000]")
        async with (
            await psycopg.AsyncConnection.connect(
                self._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection,
            connection.transaction(),
        ):
            await self._set_statement_timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT receipt_id, partition_key, payload FROM executor_receipt_outbox "
                    "WHERE published_at IS NULL AND next_attempt_at <= clock_timestamp() "
                    "ORDER BY created_at, receipt_id FOR UPDATE SKIP LOCKED LIMIT %s",
                    (limit,),
                )
            ).fetchall()
            if rows:
                await connection.execute(
                    "UPDATE executor_receipt_outbox SET attempt_count = attempt_count + 1, "
                    "next_attempt_at = clock_timestamp() + INTERVAL '5 seconds' "
                    "WHERE receipt_id = ANY(%s)",
                    ([row["receipt_id"] for row in rows],),
                )
        pending: list[PendingExecutorReceipt] = []
        for row in rows:
            stored = _json_object(row["payload"], record_name="receipt outbox payload")
            payload, command_id, command_offset = _decode_receipt_outbox_record(stored)
            pending.append(
                PendingExecutorReceipt(
                    receipt_id=row["receipt_id"],
                    partition_key=str(row["partition_key"]),
                    payload=payload,
                    command_id=command_id,
                    command_offset=command_offset,
                )
            )
        return tuple(pending)

    async def mark_receipt_published(self, receipt_id: UUID) -> None:
        """Record broker acknowledgement idempotently."""
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await self._set_statement_timeout(connection)
            await connection.execute(
                "UPDATE executor_receipt_outbox SET published_at = clock_timestamp() "
                "WHERE receipt_id = %s AND published_at IS NULL",
                (receipt_id,),
            )

    async def _set_statement_timeout(
        self,
        connection: psycopg.AsyncConnection[Any],
    ) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )

    async def _append_audit(
        self,
        connection: psycopg.AsyncConnection[Any],
        payload: Mapping[str, Any],
    ) -> None:
        mode = str(payload.get("mode", "shadow"))
        if mode not in {"shadow", "enforce"}:
            raise ValueError("audit entry mode MUST be 'shadow' or 'enforce'")
        await connection.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (_AUDIT_APPEND_LOCK_KEY,),
        )
        cursor = await connection.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        previous_hash = row[0] if row is not None else _GENESIS_HASH
        entry_hash = _next_hash(previous_hash, payload)
        await connection.execute(
            """
            INSERT INTO audit_log
                (event_id, correlation_id, actor, action_kind, mode,
                 entry, previous_hash, entry_hash)
            VALUES
                (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                _audit_event_id(payload),
                payload.get("correlation_id"),
                _first_text(payload, ("actor", "actor_oid", "producer_principal"), "fdai.system"),
                _first_text(payload, ("action_kind", "kind", "event_type"), "audit.record"),
                mode,
                _canonical(payload),
                previous_hash,
                entry_hash,
            ),
        )


def _canonical(entry: Mapping[str, Any]) -> str:
    return json.dumps(dict(entry), sort_keys=True, separators=(",", ":"), default=str)


def _next_hash(previous_hash: str, entry: Mapping[str, Any]) -> str:
    content = (previous_hash + _canonical(entry)).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _audit_event_id(payload: Mapping[str, Any]) -> str:
    raw = payload.get("event_id")
    if raw is not None:
        try:
            return str(UUID(str(raw)))
        except ValueError:
            pass
    identity = next(
        (
            str(payload[key])
            for key in ("idempotency_key", "correlation_id", "audit_id")
            if payload.get(key)
        ),
        _canonical(payload),
    )
    return str(uuid5(NAMESPACE_URL, f"fdai.audit://{identity}"))


def _first_text(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
    fallback: str,
) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _json_object(value: object, *, record_name: str) -> Mapping[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError(f"Executor {record_name} is not a JSON object")


def _receipt_outbox_record(
    payload: Mapping[str, Any],
    *,
    command_id: str,
    command_offset: int | None,
) -> Mapping[str, Any]:
    return {
        "receipt": dict(payload),
        "telemetry": {
            "command_id": command_id,
            "command_offset": command_offset,
        },
    }


def _decode_receipt_outbox_record(
    stored: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str | None, int | None]:
    receipt = stored.get("receipt")
    if receipt is None:
        legacy_command_id = stored.get("command_id")
        return (
            dict(stored),
            legacy_command_id if isinstance(legacy_command_id, str) else None,
            None,
        )
    telemetry = stored.get("telemetry")
    if not isinstance(receipt, Mapping) or not isinstance(telemetry, Mapping):
        raise RuntimeError("Executor receipt outbox envelope is malformed")
    command_id = telemetry.get("command_id")
    command_offset = telemetry.get("command_offset")
    if not isinstance(command_id, str) or not command_id:
        raise RuntimeError("Executor receipt outbox command id is missing")
    if isinstance(command_offset, bool) or not isinstance(command_offset, (int, type(None))):
        raise RuntimeError("Executor receipt outbox command offset is malformed")
    return dict(receipt), command_id, command_offset


__all__ = ["PostgresStateStore", "PostgresStateStoreConfig"]
