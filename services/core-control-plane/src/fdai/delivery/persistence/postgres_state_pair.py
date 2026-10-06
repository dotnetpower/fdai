"""Transactional paired state writes for the Postgres StateStore."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class _RollbackTransactionError(RuntimeError):
    """Abort a multi-row state write without committing a partial update."""


class PostgresStatePairMixin:
    """Mixin for authority records that must become visible together."""

    async def compare_and_set_state_with_audit_and_insert(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        insert_key: str,
        insert_value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if expected_revision < 0:
            raise ValueError("expected_revision MUST be >= 0")
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    if not await _insert_state(conn, insert_key, insert_value):
                        return False
                    if not await _update_state_revision(conn, key, value, expected_revision):
                        raise _RollbackTransactionError()
                    await self._append_audit_in_transaction(conn, dict(audit_entry))
        except _RollbackTransactionError:
            return False
        return True

    async def write_state_pair_with_audit_if_absent(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        insert_key: str,
        insert_value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    if not await _insert_state(conn, key, value):
                        raise _RollbackTransactionError()
                    if not await _insert_state(conn, insert_key, insert_value):
                        raise _RollbackTransactionError()
                    await self._append_audit_in_transaction(conn, dict(audit_entry))
        except _RollbackTransactionError:
            return False
        return True


async def _insert_state(conn: Any, key: str, value: Mapping[str, Any]) -> bool:
    cursor = await conn.execute(
        """
        INSERT INTO state_kv (key, value)
        VALUES (%s, %s::jsonb)
        ON CONFLICT (key) DO NOTHING
        RETURNING key
        """,
        (key, json.dumps(dict(value), default=str)),
    )
    return await cursor.fetchone() is not None


async def _update_state_revision(
    conn: Any,
    key: str,
    value: Mapping[str, Any],
    expected_revision: int,
) -> bool:
    cursor = await conn.execute(
        """
        UPDATE state_kv
           SET value = %s::jsonb,
               updated_at = NOW()
         WHERE key = %s
           AND COALESCE(value ->> 'revision', '0') = %s
        RETURNING key
        """,
        (json.dumps(dict(value), default=str), key, str(expected_revision)),
    )
    return await cursor.fetchone() is not None
