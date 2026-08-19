"""Persist Operator-owned verified principal-to-channel bindings."""

# ruff: noqa: S608 - interpolated projection and state clauses are module constants.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelBindingState,
    ChannelKind,
    PrincipalChannelBinding,
    VerifiedChannelEndpoint,
)
from psycopg.rows import dict_row

_BINDING_COLUMNS: Final = (
    "binding_id, principal_id, scope_ref, conversation_id, channel_kind, channel_id, "
    "sender_id, thread_id, verification_ref, verified_at, created_by, created_at, "
    "resumed_from_binding_id, state, revoked_by, revoked_at"
)


class PrincipalChannelBindingError(RuntimeError):
    """A binding identity conflicts with existing durable endpoint ownership."""


@dataclass(frozen=True, slots=True)
class PostgresChannelBindingConfig:
    """Configure bounded PostgreSQL connections for verified bindings."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("channel binding dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("channel binding timeouts MUST be positive")


class PostgresPrincipalChannelBindingStore:
    """Persist verified endpoints with active uniqueness and revocation CAS."""

    def __init__(self, *, config: PostgresChannelBindingConfig) -> None:
        self._config = config

    async def probe_readiness(self) -> bool:
        """Verify runtime-role access to the verified binding table."""
        try:
            async with await self._connect() as connection:
                await self._set_timeout(connection)
                await connection.execute("SELECT 1 FROM principal_conversation_binding LIMIT 0")
            return True
        except psycopg.Error:
            return False

    async def create(self, binding: PrincipalChannelBinding) -> PrincipalChannelBinding:
        """Insert one immutable binding or return its exact idempotent replay."""
        endpoint = binding.endpoint
        try:
            async with await self._connect() as connection, connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "INSERT INTO principal_conversation_binding ("
                    f"{_BINDING_COLUMNS}) VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (binding_id) DO NOTHING "
                    f"RETURNING {_BINDING_COLUMNS}",
                    (
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
                    ),
                )
                row = await cursor.fetchone()
                if row is not None:
                    return _binding(row)
                current = await self._get_locked(connection, binding.binding_id)
                if current != binding:
                    raise PrincipalChannelBindingError(
                        "binding id was reused with different immutable content"
                    )
                return current
        except psycopg.errors.UniqueViolation as exc:
            raise PrincipalChannelBindingError(
                "an active binding already owns the verified endpoint"
            ) from exc

    async def get(self, binding_id: str) -> PrincipalChannelBinding | None:
        """Read one binding by its stable server-owned id."""
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_BINDING_COLUMNS} FROM principal_conversation_binding "
                "WHERE binding_id = %s",
                (binding_id,),
            )
            row = await cursor.fetchone()
            return _binding(row) if row is not None else None

    async def revoke(
        self,
        *,
        binding_id: str,
        expected_state: ChannelBindingState,
        actor_id: str,
        at: datetime,
    ) -> PrincipalChannelBinding | None:
        """Compare-and-set an active binding to revoked without deleting evidence."""
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "UPDATE principal_conversation_binding "
                "SET state = %s, revoked_by = %s, revoked_at = %s "
                "WHERE binding_id = %s AND state = %s "
                f"RETURNING {_BINDING_COLUMNS}",
                (
                    ChannelBindingState.REVOKED.value,
                    actor_id,
                    at,
                    binding_id,
                    expected_state.value,
                ),
            )
            row = await cursor.fetchone()
            return _binding(row) if row is not None else None

    async def list_for_principal(
        self,
        *,
        principal_id: str,
        include_revoked: bool = False,
    ) -> tuple[PrincipalChannelBinding, ...]:
        """List one principal's bindings without crossing principal scope."""
        state_clause = "" if include_revoked else " AND state = 'active'"
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_BINDING_COLUMNS} FROM principal_conversation_binding "
                f"WHERE principal_id = %s{state_clause} "
                "ORDER BY created_at DESC, binding_id",
                (principal_id,),
            )
            return tuple(_binding(row) for row in await cursor.fetchall())

    async def _get_locked(
        self,
        connection: psycopg.AsyncConnection[Any],
        binding_id: str,
    ) -> PrincipalChannelBinding:
        cursor = await connection.execute(
            f"SELECT {_BINDING_COLUMNS} FROM principal_conversation_binding "
            "WHERE binding_id = %s FOR UPDATE",
            (binding_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise PrincipalChannelBindingError("binding disappeared during create")
        return _binding(row)

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


def _binding(row: dict[str, Any]) -> PrincipalChannelBinding:
    endpoint = VerifiedChannelEndpoint(
        principal_id=str(row["principal_id"]),
        scope_ref=str(row["scope_ref"]),
        channel_kind=ChannelKind(str(row["channel_kind"])),
        channel_id=str(row["channel_id"]),
        sender_id=str(row["sender_id"]),
        thread_id=str(row["thread_id"]) if row["thread_id"] is not None else None,
        verification_ref=str(row["verification_ref"]),
        verified_at=row["verified_at"],
    )
    return PrincipalChannelBinding(
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
        state=ChannelBindingState(str(row["state"])),
        revoked_by=str(row["revoked_by"]) if row["revoked_by"] is not None else None,
        revoked_at=row["revoked_at"],
    )


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


__all__ = [
    "PostgresChannelBindingConfig",
    "PostgresPrincipalChannelBindingStore",
    "PrincipalChannelBindingError",
]
