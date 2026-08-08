"""PostgreSQL atomic idempotency claims for side-effect RPC methods."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.rpc import RpcResponse


@dataclass(frozen=True, slots=True)
class PostgresRpcIdempotencyStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresRpcIdempotencyStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresRpcIdempotencyStoreConfig timeouts MUST be positive")


class RpcClaimConflictError(RuntimeError):
    """An RPC claim could not transition from claimed to completed."""


class PostgresRpcIdempotencyStore:
    """Hash raw keys and persist claim/completion across replicas and restarts."""

    def __init__(self, *, config: PostgresRpcIdempotencyStoreConfig) -> None:
        self._config = config

    async def get(self, key: str) -> RpcResponse | None:
        key_sha256 = _key_digest(key)
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT state, response FROM rpc_idempotency_claim WHERE key_sha256 = %s",
                (key_sha256,),
            )
            row = await cursor.fetchone()
        if row is None or row["state"] != "completed":
            return None
        return _response_from_payload(row["response"])

    async def claim(self, key: str) -> bool:
        key_sha256 = _key_digest(key)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO rpc_idempotency_claim (key_sha256, state)
                VALUES (%s, 'claimed')
                ON CONFLICT (key_sha256) DO NOTHING
                RETURNING key_sha256
                """,
                (key_sha256,),
            )
            row = await cursor.fetchone()
        return row is not None

    async def complete(self, key: str, response: RpcResponse) -> None:
        key_sha256 = _key_digest(key)
        payload = json.dumps(response.to_dict(), sort_keys=True, separators=(",", ":"))
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                UPDATE rpc_idempotency_claim
                   SET state = 'completed', response = %s::jsonb, completed_at = now()
                 WHERE key_sha256 = %s AND state = 'claimed'
                 RETURNING key_sha256
                """,
                (payload, key_sha256),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RpcClaimConflictError("RPC idempotency claim is missing or already completed")

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _key_digest(key: str) -> str:
    if not key or len(key) > 512:
        raise ValueError("RPC idempotency claim key MUST be non-empty and bounded")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _response_from_payload(value: object) -> RpcResponse:
    if not isinstance(value, dict):
        raise RuntimeError("stored RPC response is not an object")
    request_id = value.get("request_id")
    ok = value.get("ok")
    result = value.get("result")
    error = value.get("error")
    if (
        value.get("schema_version") != "1.0.0"
        or not isinstance(request_id, str)
        or not isinstance(ok, bool)
        or not isinstance(result, dict)
    ):
        raise RuntimeError("stored RPC response is invalid")
    error_code: str | None = None
    error_message: str | None = None
    if error is not None:
        if not isinstance(error, dict):
            raise RuntimeError("stored RPC error is invalid")
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            raise RuntimeError("stored RPC error is incomplete")
        error_code = code
        error_message = message
    return RpcResponse(
        request_id=request_id,
        ok=ok,
        result=result,
        error_code=error_code,
        error_message=error_message,
    )


__all__ = [
    "PostgresRpcIdempotencyStore",
    "PostgresRpcIdempotencyStoreConfig",
    "RpcClaimConflictError",
]
