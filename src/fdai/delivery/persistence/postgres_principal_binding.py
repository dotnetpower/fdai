"""PostgreSQL persistence for verified principal conversation bindings."""

# ruff: noqa: S608 - SQL identifiers are module constants; runtime values are parametrized.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.conversation.principal_binding import PrincipalConversationBindingStore
from fdai.shared.providers.conversation_channel import ConversationChannelKind
from fdai.shared.providers.conversation_delivery import (
    PrincipalConversationBinding,
    PrincipalConversationBindingState,
    VerifiedChannelEndpoint,
)

_COLUMNS: Final = (
    "binding_id, principal_id, scope_ref, conversation_id, channel_kind, channel_id, "
    "sender_id, thread_id, verification_ref, verified_at, created_by, created_at, "
    "resumed_from_binding_id, state, revoked_by, revoked_at"
)


@dataclass(frozen=True, slots=True)
class PostgresPrincipalConversationBindingStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("binding store dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("binding store timeouts MUST be positive")


class PostgresPrincipalConversationBindingStore(PrincipalConversationBindingStore):
    """Durable binding store with idempotent create and revoke CAS."""

    def __init__(self, *, config: PostgresPrincipalConversationBindingStoreConfig) -> None:
        self._config = config

    async def create(
        self,
        binding: PrincipalConversationBinding,
    ) -> PrincipalConversationBinding:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                f"INSERT INTO principal_conversation_binding ({_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (binding_id) DO NOTHING RETURNING binding_id",  # noqa: S608
                _values(binding),
            )
            if await cursor.fetchone() is not None:
                return binding
            current = await self._select(connection, binding.binding_id)
            if current != binding:
                raise ValueError("binding id was reused with different immutable content")
            return current

    async def get(self, binding_id: str) -> PrincipalConversationBinding | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._select(connection, binding_id)

    async def revoke(
        self,
        *,
        binding_id: str,
        expected_state: PrincipalConversationBindingState,
        actor_id: str,
        at: datetime,
    ) -> PrincipalConversationBinding | None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE principal_conversation_binding "
                "SET state = 'revoked', revoked_by = %s, revoked_at = %s "
                "WHERE binding_id = %s AND state = %s "
                f"RETURNING {_COLUMNS}",  # noqa: S608
                (actor_id, at, binding_id, expected_state.value),
            )
            row = await cursor.fetchone()
        return _row_to_binding(row) if row is not None else None

    async def list_for_principal(
        self,
        *,
        principal_id: str,
        include_revoked: bool = False,
    ) -> tuple[PrincipalConversationBinding, ...]:
        state_clause = "" if include_revoked else "AND state = 'active'"
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM principal_conversation_binding "
                f"WHERE principal_id = %s {state_clause} "
                "ORDER BY created_at DESC, binding_id",  # noqa: S608
                (principal_id,),
            )
            return tuple(_row_to_binding(row) for row in await cursor.fetchall())

    async def _select(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        binding_id: str,
    ) -> PrincipalConversationBinding | None:
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM principal_conversation_binding WHERE binding_id = %s",  # noqa: S608
            (binding_id,),
        )
        row = await cursor.fetchone()
        return _row_to_binding(row) if row is not None else None

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _values(binding: PrincipalConversationBinding) -> tuple[object, ...]:
    endpoint = binding.endpoint
    return (
        binding.binding_id,
        binding.principal_id,
        binding.scope_ref,
        binding.conversation_id,
        endpoint.channel_kind.value,
        endpoint.channel_id,
        endpoint.sender_id,
        endpoint.thread_id,
        endpoint.verification_ref,
        endpoint.verified_at,
        binding.created_by,
        binding.created_at,
        binding.resumed_from_binding_id,
        binding.state.value,
        binding.revoked_by,
        binding.revoked_at,
    )


def _row_to_binding(row: dict[str, Any]) -> PrincipalConversationBinding:
    endpoint = VerifiedChannelEndpoint(
        principal_id=str(row["principal_id"]),
        scope_ref=str(row["scope_ref"]),
        channel_kind=ConversationChannelKind(str(row["channel_kind"])),
        channel_id=str(row["channel_id"]),
        sender_id=str(row["sender_id"]),
        thread_id=str(row["thread_id"]) if row["thread_id"] is not None else None,
        verification_ref=str(row["verification_ref"]),
        verified_at=row["verified_at"],
    )
    return PrincipalConversationBinding(
        binding_id=str(row["binding_id"]),
        principal_id=str(row["principal_id"]),
        scope_ref=str(row["scope_ref"]),
        conversation_id=str(row["conversation_id"]),
        endpoint=endpoint,
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        resumed_from_binding_id=(
            str(row["resumed_from_binding_id"])
            if row["resumed_from_binding_id"] is not None
            else None
        ),
        state=PrincipalConversationBindingState(str(row["state"])),
        revoked_by=str(row["revoked_by"]) if row["revoked_by"] is not None else None,
        revoked_at=row["revoked_at"],
    )


__all__ = [
    "PostgresPrincipalConversationBindingStore",
    "PostgresPrincipalConversationBindingStoreConfig",
]
