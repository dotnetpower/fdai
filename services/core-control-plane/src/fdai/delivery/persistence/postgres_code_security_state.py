"""StateStore adapter for a code-security role with no direct shared-table access."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres import PostgresStateStore
from fdai.delivery.persistence.postgres_audit_fields import audit_event_id
from fdai.shared.providers.audit_hash import canonical_entry, next_hash


class PostgresCodeSecurityStateStore(PostgresStateStore):
    """Use fixed-parameter, scoped database functions, including atomic state-plus-audit writes.

    Every transaction explicitly assumes the worker role, requiring membership granted to the
    authenticated deployment identity. Other inherited operations have no shared-table access.
    Missing membership or migrations fail; the adapter never falls back to the Core role.
    """

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[psycopg.AsyncConnection[dict[str, Any]]]:
        async with super()._connection() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE fdai_code_security_worker")
                yield conn

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    "SELECT public.fdai_code_security_state_read(%s) AS value", (key,)
                )
                row = await cursor.fetchone()
        value = row["value"] if row else None
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("code-security state is not a JSON object")
        return value

    async def read_states(self, prefix: str, *, limit: int) -> tuple[Mapping[str, Any], ...]:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                cursor = await conn.execute(
                    "SELECT value FROM public.fdai_code_security_states(%s, %s)", (prefix, limit)
                )
                rows = await cursor.fetchall()
        if any(not isinstance(row["value"], dict) for row in rows):
            raise ValueError("code-security state list contains a non-object")
        return tuple(row["value"] for row in rows)

    async def _write(
        self,
        conn: psycopg.AsyncConnection[Any],
        key: str,
        value: Mapping[str, Any],
        operation: str,
        revision: int | None = None,
    ) -> bool:
        cursor = await conn.execute(
            "SELECT public.fdai_code_security_state_write(%s, %s::jsonb, %s, %s) AS written",
            (key, json.dumps(dict(value)), operation, revision),
        )
        row = await cursor.fetchone()
        if row is None or not isinstance(row["written"], bool):
            raise ValueError("code-security state write returned no boolean")
        return row["written"]

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                await self._write(conn, key, value, "upsert")

    async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                return await self._write(conn, key, value, "insert")

    async def write_state_with_audit_if_absent(
        self, key: str, value: Mapping[str, Any], audit_entry: Mapping[str, Any]
    ) -> bool:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                if not await self._write(conn, key, value, "insert"):
                    return False
                await self._append_audit_in_transaction(conn, audit_entry)
                return True

    async def compare_and_set_state(
        self, key: str, value: Mapping[str, Any], *, expected_revision: int
    ) -> bool:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                return await self._write(conn, key, value, "cas", expected_revision)

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        async with self._connection() as conn:
            async with conn.transaction():
                await self._set_statement_timeout(conn)
                if not await self._write(conn, key, value, "cas", expected_revision):
                    return False
                await self._append_audit_in_transaction(conn, audit_entry)
                return True

    async def _append_audit_in_transaction(
        self, conn: psycopg.AsyncConnection[Any], payload: Mapping[str, Any]
    ) -> None:
        cursor = await conn.execute("SELECT public.fdai_code_security_audit_head() AS hash")
        row = await cursor.fetchone()
        if row is None or not isinstance(row["hash"], str):
            raise ValueError("code-security audit head is unavailable")
        previous = row["hash"]
        await conn.execute(
            "SELECT public.fdai_code_security_audit_append(%s, %s, %s, %s::uuid)",
            (
                canonical_entry(payload),
                previous,
                next_hash(previous, payload),
                audit_event_id(payload),
            ),
        )
