"""Persist Operator-owned inbound channel processing claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class PostgresChannelMessageLedgerConfig:
    """Configure bounded PostgreSQL connections and inbound processing leases."""

    dsn: str
    lease_seconds: int = 300
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("channel message ledger dsn MUST NOT be empty")
        if not 1 <= self.lease_seconds <= 3600:
            raise ValueError("channel message lease_seconds is outside the bounded range")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("channel message ledger timeouts MUST be positive")


class PostgresChannelMessageLedger:
    """Reclaim expired processing leases while preserving completed dedupe."""

    def __init__(self, *, config: PostgresChannelMessageLedgerConfig) -> None:
        self._config = config

    async def probe_readiness(self) -> bool:
        """Verify runtime-role access to the inbound ownership table."""
        try:
            async with await self._connect() as connection:
                await self._set_timeout(connection)
                await connection.execute("SELECT 1 FROM conversation_channel_message_claim LIMIT 0")
            return True
        except psycopg.Error:
            return False

    async def claim(self, idempotency_key: str) -> bool:
        """Claim a new or expired processing record using the database clock."""
        _validate_key(idempotency_key)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO conversation_channel_message_claim (
                    idempotency_key, state, claimed_at, lease_expires_at, completed_at
                ) VALUES (%s, 'processing', now(), now() + (%s * interval '1 second'), NULL)
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    state = 'processing',
                    claimed_at = now(),
                    lease_expires_at = now() + (%s * interval '1 second'),
                    completed_at = NULL
                WHERE conversation_channel_message_claim.state = 'processing'
                  AND conversation_channel_message_claim.lease_expires_at <= now()
                RETURNING idempotency_key
                """,
                (idempotency_key, self._config.lease_seconds, self._config.lease_seconds),
            )
            return await cursor.fetchone() is not None

    async def complete(self, idempotency_key: str) -> None:
        """Close one active processing claim as permanent duplicate suppression."""
        _validate_key(idempotency_key)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                UPDATE conversation_channel_message_claim
                   SET state = 'completed', lease_expires_at = NULL, completed_at = now()
                 WHERE idempotency_key = %s AND state = 'processing'
                """,
                (idempotency_key,),
            )
            if cursor.rowcount != 1:
                raise ValueError("channel message completion claim is unavailable")

    async def release(self, idempotency_key: str) -> None:
        """Delete only a nonterminal processing claim so safe work can retry."""
        _validate_key(idempotency_key)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await connection.execute(
                "DELETE FROM conversation_channel_message_claim "
                "WHERE idempotency_key = %s AND state = 'processing'",
                (idempotency_key,),
            )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            _psycopg_dsn(self._config.dsn),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _validate_key(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("channel message idempotency key MUST be a lowercase SHA-256 digest")


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


__all__ = ["PostgresChannelMessageLedger", "PostgresChannelMessageLedgerConfig"]
