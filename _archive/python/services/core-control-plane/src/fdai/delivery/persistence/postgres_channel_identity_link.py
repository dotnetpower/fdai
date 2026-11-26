"""PostgreSQL persistence for explicit cross-channel identity links."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.conversation import ChannelSenderKey, CrossChannelIdentityLink
from fdai.shared.providers.conversation_channel import ConversationChannelKind

_COLUMNS: Final = (
    "link_id, principal_id, first_channel_kind, first_channel_id, first_sender_id, "
    "second_channel_kind, second_channel_id, second_sender_id, approved_by, created_at"
)


@dataclass(frozen=True, slots=True)
class PostgresChannelIdentityLinkStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresChannelIdentityLinkStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresChannelIdentityLinkStoreConfig timeouts MUST be positive")


class PostgresChannelIdentityLinkStore:
    """Durable idempotent link records; sender mappings remain separate."""

    def __init__(self, *, config: PostgresChannelIdentityLinkStoreConfig) -> None:
        self._config = config

    async def create(self, link: CrossChannelIdentityLink) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO channel_identity_link (
                    link_id, principal_id,
                    first_channel_kind, first_channel_id, first_sender_id,
                    second_channel_kind, second_channel_id, second_sender_id,
                    approved_by, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (link_id) DO NOTHING
                """,
                (
                    link.link_id,
                    link.principal_id,
                    link.first.channel_kind.value,
                    link.first.channel_id,
                    link.first.sender_id,
                    link.second.channel_kind.value,
                    link.second.channel_id,
                    link.second.sender_id,
                    link.approved_by,
                    link.created_at,
                ),
            )
        return cursor.rowcount == 1

    async def get(self, link_id: str) -> CrossChannelIdentityLink | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM channel_identity_link WHERE link_id = %s",  # noqa: S608
                (link_id,),
            )
            row = await cursor.fetchone()
        return _row_to_link(row) if row is not None else None

    async def list_for_principal(
        self,
        principal_id: str,
    ) -> Sequence[CrossChannelIdentityLink]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM channel_identity_link "  # noqa: S608
                "WHERE principal_id = %s ORDER BY created_at, link_id",
                (principal_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_link(row) for row in rows)

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


def _row_to_link(row: dict[str, Any]) -> CrossChannelIdentityLink:
    return CrossChannelIdentityLink(
        link_id=str(row["link_id"]),
        principal_id=str(row["principal_id"]),
        first=ChannelSenderKey(
            ConversationChannelKind(str(row["first_channel_kind"])),
            str(row["first_channel_id"]),
            str(row["first_sender_id"]),
        ),
        second=ChannelSenderKey(
            ConversationChannelKind(str(row["second_channel_kind"])),
            str(row["second_channel_id"]),
            str(row["second_sender_id"]),
        ),
        approved_by=str(row["approved_by"]),
        created_at=row["created_at"],
    )


__all__ = ["PostgresChannelIdentityLinkStore", "PostgresChannelIdentityLinkStoreConfig"]
