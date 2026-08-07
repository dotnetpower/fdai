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


__all__ = ["PostgresStateStore", "PostgresStateStoreConfig"]
