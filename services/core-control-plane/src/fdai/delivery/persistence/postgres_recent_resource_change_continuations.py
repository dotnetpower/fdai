"""PostgreSQL-backed Core continuation store for recent Resource change pages."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.ontology_platform.recent_resource_change_continuations import (
    RecentResourceChangeContinuationStore,
    StoredRecentResourceChangeContinuation,
    decode_stored_continuation,
    encode_stored_continuation,
)


@dataclass(frozen=True, slots=True)
class PostgresRecentResourceChangeContinuationStoreConfig:
    dsn: str
    statement_timeout_ms: int = 5_000
    connect_timeout_s: int = 5

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("recent Resource change continuation DSN MUST NOT be empty")
        if not 1 <= self.statement_timeout_ms <= 10_000 or not 1 <= self.connect_timeout_s <= 10:
            raise ValueError("recent Resource change continuation deadlines are out of bounds")


class PostgresRecentResourceChangeContinuationStore(RecentResourceChangeContinuationStore):
    """Store opaque continuation references without exposing their content to clients."""

    def __init__(self, *, config: PostgresRecentResourceChangeContinuationStoreConfig) -> None:
        self._config = config

    async def put(self, record: StoredRecentResourceChangeContinuation) -> None:
        async with await self._connect() as connection:
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                (
                    _key(record.continuation_ref),
                    Jsonb(_json_payload(record)),
                ),
            )

    async def get(self, continuation_ref: str) -> StoredRecentResourceChangeContinuation | None:
        async with await self._connect() as connection:
            cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key=%s",
                (_key(continuation_ref),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return decode_stored_continuation(_canonical_payload(row["value"]))

    async def delete(self, continuation_ref: str) -> None:
        async with await self._connect() as connection:
            await connection.execute(
                "DELETE FROM state_kv WHERE key=%s",
                (_key(continuation_ref),),
            )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, object]]:
        connection = await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )
        return connection


def _json_payload(record: StoredRecentResourceChangeContinuation) -> object:
    import json

    return json.loads(encode_stored_continuation(record))


def _key(continuation_ref: str) -> str:
    return f"query-continuation:recent-resource-changes:{continuation_ref}"


def _canonical_payload(value: object) -> str:
    import json

    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


__all__ = [
    "PostgresRecentResourceChangeContinuationStore",
    "PostgresRecentResourceChangeContinuationStoreConfig",
]
