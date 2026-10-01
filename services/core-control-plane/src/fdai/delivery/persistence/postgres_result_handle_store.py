"""PostgreSQL result-handle store using encrypted bodies in state_kv."""

# ruff: noqa: S608 - SQL clauses are module-owned; request values remain bound parameters.

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from fdai_service_contracts.reasoning_handles import ResultHandle, ResultHandleRef
from psycopg.rows import dict_row

from fdai.core.conversation.result_handle_store import (
    ResultHandleBinding,
    ResultHandleGetResult,
    ResultHandleGetStatus,
    ResultHandleKeyProvider,
    ResultHandleStore,
    _encrypt_handle,
    _load_record,
    _StoredHandle,
)

_INDEX_PREFIX: Final = "result-handle:index:"
_RECORD_PREFIX: Final = "result-handle:scope:"


@dataclass(frozen=True, slots=True)
class PostgresResultHandleStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresResultHandleStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresResultHandleStoreConfig timeouts MUST be positive")


class PostgresResultHandleStore(ResultHandleStore):
    """Async Core-owned PostgreSQL persistence for encrypted result handles."""

    def __init__(
        self,
        *,
        config: PostgresResultHandleStoreConfig,
        keys: ResultHandleKeyProvider,
        handle_ref_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._keys = keys
        from fdai.core.conversation.result_handle_store import _new_handle_ref

        self._handle_ref_factory = handle_ref_factory or _new_handle_ref

    async def put(
        self,
        handle: ResultHandle,
        *,
        issued_at: datetime,
        expires_at: datetime,
    ) -> ResultHandleRef:
        key = await self._keys.current_key()
        handle_ref = self._handle_ref_factory()
        envelope = _encrypt_handle(handle, key=key, handle_ref=handle_ref)
        record_key = _record_key(handle.deployment_scope_digest, handle_ref)
        index_key = _index_key(handle_ref)
        record = {
            "kind": "core.result_handle",
            "handle_ref": handle_ref,
            "record_key": record_key,
            "deployment_scope_digest": handle.deployment_scope_digest,
            "principal_digest": handle.principal_digest,
            "conversation_id": handle.conversation_id,
            "purpose": handle.purpose,
            "manifest_digest": handle.manifest_digest,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "key_version": key.key_version,
            "envelope": envelope,
        }
        index = {
            "kind": "core.result_handle.index",
            "handle_ref": handle_ref,
            "record_key": record_key,
            "deployment_scope_digest": handle.deployment_scope_digest,
            "conversation_id": handle.conversation_id,
        }
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                (record_key, json.dumps(record)),
            )
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                (index_key, json.dumps(index)),
            )
        return ResultHandleRef(
            handle_ref=handle_ref,
            key_version=key.key_version,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    async def get(
        self,
        reference: ResultHandleRef,
        *,
        binding: ResultHandleBinding,
        allowed_snapshot_fields: Iterable[str] = (),
    ) -> ResultHandleGetResult:
        async with await self._connect() as connection:
            await self._timeout(connection)
            index_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key = %s",
                (_index_key(reference.handle_ref),),
            )
            index_row = await index_cursor.fetchone()
            if index_row is None:
                return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
            index = _json_object(index_row["value"])
            record_key = index.get("record_key")
            if not isinstance(record_key, str):
                return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
            record_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key = %s",
                (record_key,),
            )
            record_row = await record_cursor.fetchone()
        if record_row is None:
            return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
        return await _load_record(
            _stored(_json_object(record_row["value"])),
            reference=reference,
            binding=binding,
            keys=self._keys,
            allowed_snapshot_fields=allowed_snapshot_fields,
        )

    async def delete_conversation(
        self,
        *,
        deployment_scope_digest: str,
        conversation_id: str,
    ) -> int:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT key, value FROM state_kv "
                "WHERE key LIKE %s "
                "AND value ->> 'kind' = 'core.result_handle' "
                "AND value ->> 'deployment_scope_digest' = %s "
                "AND value ->> 'conversation_id' = %s",
                (
                    f"{_RECORD_PREFIX}{deployment_scope_digest}:%",
                    deployment_scope_digest,
                    conversation_id,
                ),
            )
            rows = await cursor.fetchall()
            refs = tuple(str(_json_object(row["value"]).get("handle_ref")) for row in rows)
            keys = [str(row["key"]) for row in rows]
            keys.extend(_index_key(ref) for ref in refs if ref)
            if keys:
                await connection.execute(
                    "DELETE FROM state_kv WHERE key = ANY(%s::text[])", (keys,)
                )
        return len(rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _index_key(handle_ref: str) -> str:
    return f"{_INDEX_PREFIX}{handle_ref}"


def _record_key(deployment_scope_digest: str, handle_ref: str) -> str:
    return f"{_RECORD_PREFIX}{deployment_scope_digest}:{handle_ref}"


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ValueError("result handle state record MUST be a JSON object")
    return dict(parsed)


def _stored(value: dict[str, Any]) -> _StoredHandle:
    return _StoredHandle(
        handle_ref=str(value["handle_ref"]),
        deployment_scope_digest=str(value["deployment_scope_digest"]),
        principal_digest=str(value["principal_digest"]),
        conversation_id=str(value["conversation_id"]),
        purpose=str(value["purpose"]),
        manifest_digest=str(value["manifest_digest"]),
        issued_at=datetime.fromisoformat(str(value["issued_at"])),
        expires_at=datetime.fromisoformat(str(value["expires_at"])),
        key_version=str(value["key_version"]),
        envelope=_json_object(value["envelope"]),
    )


__all__ = ["PostgresResultHandleStore", "PostgresResultHandleStoreConfig"]
