"""PostgreSQL persistence for channel sender pairing requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.conversation.channel_access import (
    ChannelSenderKey,
    PairingCreateResult,
    PairingRequest,
)
from fdai.shared.providers.conversation_channel import ConversationChannelKind

_COLUMNS: Final = (
    "channel_kind, channel_id, sender_id, code_digest, created_at, expires_at, "
    "approved_principal_id, approved_at"
)


@dataclass(frozen=True, slots=True)
class PostgresChannelPairingStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresChannelPairingStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresChannelPairingStoreConfig timeouts MUST be positive")


class PostgresChannelPairingStore:
    """Durable pairing store with channel-scoped atomic pending caps."""

    def __init__(self, *, config: PostgresChannelPairingStoreConfig) -> None:
        self._config = config

    async def get(self, sender: ChannelSenderKey) -> PairingRequest | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM channel_pairing_request "  # noqa: S608
                "WHERE channel_kind = %s AND channel_id = %s AND sender_id = %s",
                _sender_values(sender),
            )
            row = await cursor.fetchone()
        return _row_to_request(row) if row is not None else None

    async def create_pending(
        self,
        request: PairingRequest,
        *,
        max_pending: int,
    ) -> PairingCreateResult:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"channel-pairing:{request.sender.channel_kind.value}",),
            )
            current_cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM channel_pairing_request "  # noqa: S608
                "WHERE channel_kind = %s AND channel_id = %s AND sender_id = %s FOR UPDATE",
                _sender_values(request.sender),
            )
            current_row = await current_cursor.fetchone()
            if current_row is not None:
                current = _row_to_request(current_row)
                if current.approved:
                    return PairingCreateResult.ALREADY_APPROVED
                if request.created_at < current.expires_at:
                    return PairingCreateResult.ALREADY_PENDING
            count_cursor = await connection.execute(
                "SELECT count(*) AS pending_count FROM channel_pairing_request "
                "WHERE channel_kind = %s AND approved_principal_id IS NULL AND expires_at > %s",
                (request.sender.channel_kind.value, request.created_at),
            )
            count_row = await count_cursor.fetchone()
            if count_row is None or int(count_row["pending_count"]) >= max_pending:
                return PairingCreateResult.CAP_REACHED
            await connection.execute(
                """
                INSERT INTO channel_pairing_request (
                    channel_kind, channel_id, sender_id, code_digest, created_at, expires_at,
                    approved_principal_id, approved_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL)
                ON CONFLICT (channel_kind, channel_id, sender_id) DO UPDATE SET
                    code_digest = EXCLUDED.code_digest,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at,
                    approved_principal_id = NULL,
                    approved_at = NULL,
                    updated_at = now()
                """,
                (
                    request.sender.channel_kind.value,
                    request.sender.channel_id,
                    request.sender.sender_id,
                    request.code_digest,
                    request.created_at,
                    request.expires_at,
                ),
            )
        return PairingCreateResult.CREATED

    async def approve_pending(
        self,
        sender: ChannelSenderKey,
        *,
        code_digest: str,
        principal_id: str,
        at: datetime,
    ) -> PairingRequest | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                UPDATE channel_pairing_request
                   SET approved_principal_id = %s, approved_at = %s, updated_at = now()
                 WHERE channel_kind = %s AND channel_id = %s AND sender_id = %s
                   AND code_digest = %s AND approved_principal_id IS NULL AND expires_at > %s
                 RETURNING {_COLUMNS}
                """,  # noqa: S608 - _COLUMNS is a module constant
                (
                    principal_id,
                    at,
                    *_sender_values(sender),
                    code_digest,
                    at,
                ),
            )
            row = await cursor.fetchone()
        return _row_to_request(row) if row is not None else None

    async def cancel_pending(
        self,
        sender: ChannelSenderKey,
        *,
        code_digest: str,
    ) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "DELETE FROM channel_pairing_request "
                "WHERE channel_kind = %s AND channel_id = %s AND sender_id = %s "
                "AND code_digest = %s AND approved_principal_id IS NULL",
                (*_sender_values(sender), code_digest),
            )
        return cursor.rowcount == 1

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


def _sender_values(sender: ChannelSenderKey) -> tuple[str, str, str]:
    return sender.channel_kind.value, sender.channel_id, sender.sender_id


def _row_to_request(row: dict[str, Any]) -> PairingRequest:
    return PairingRequest(
        sender=ChannelSenderKey(
            channel_kind=ConversationChannelKind(str(row["channel_kind"])),
            channel_id=str(row["channel_id"]),
            sender_id=str(row["sender_id"]),
        ),
        code_digest=str(row["code_digest"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        approved_principal_id=(
            str(row["approved_principal_id"]) if row["approved_principal_id"] is not None else None
        ),
        approved_at=row["approved_at"],
    )


__all__ = ["PostgresChannelPairingStore", "PostgresChannelPairingStoreConfig"]
