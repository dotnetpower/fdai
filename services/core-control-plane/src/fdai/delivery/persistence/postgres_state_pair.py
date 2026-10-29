"""Transactional paired state writes for the Postgres StateStore."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any


class _RollbackTransactionError(RuntimeError):
    """Abort a multi-row state write without committing a partial update."""


class PostgresStatePairMixin:
    """Mixin for authority records that must become visible together."""

    async def compare_and_set_state_pair_with_audit(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        second_key: str,
        second_value: Mapping[str, Any],
        expected_second_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if expected_revision < 0 or expected_second_revision < 0 or key == second_key:
            raise ValueError("state pair expected revisions or keys are invalid")
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    first_changed = await _write_state_revision(conn, key, value, expected_revision)
                    second_changed = await _write_state_revision(
                        conn, second_key, second_value, expected_second_revision
                    )
                    if not first_changed or not second_changed:
                        raise _RollbackTransactionError()
                    await self._append_audit_in_transaction(conn, dict(audit_entry))
        except _RollbackTransactionError:
            return False
        return True

    async def compare_and_set_state_with_audit_and_insert(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        insert_key: str,
        insert_value: Mapping[str, Any],
        insert_key_2: str | None = None,
        insert_value_2: Mapping[str, Any] | None = None,
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
                    if insert_key_2 is not None and insert_value_2 is not None:
                        if not await _upsert_state_when_field_matches(
                            conn,
                            insert_key_2,
                            insert_value_2,
                            field="approval_profile_digest",
                        ):
                            raise _RollbackTransactionError()
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
        insert_key_2: str | None = None,
        insert_value_2: Mapping[str, Any] | None = None,
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
                    if insert_key_2 is not None and insert_value_2 is not None:
                        if not await _upsert_state_when_field_matches(
                            conn,
                            insert_key_2,
                            insert_value_2,
                            field="approval_profile_digest",
                        ):
                            raise _RollbackTransactionError()
                    await self._append_audit_in_transaction(conn, dict(audit_entry))
        except _RollbackTransactionError:
            return False
        return True

    async def compare_and_set_state_with_audit_and_insert_before(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        insert_key: str,
        insert_value: Mapping[str, Any],
        not_before: datetime,
        expires_at: datetime,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if expected_revision < 0:
            raise ValueError("expected_revision MUST be >= 0")
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    cursor = await conn.execute(
                        """
                        UPDATE state_kv
                           SET value = %s::jsonb,
                               updated_at = clock_timestamp()
                         WHERE key = %s
                           AND COALESCE(value ->> 'revision', '0') = %s
                           AND %s <= clock_timestamp()
                           AND clock_timestamp() < %s
                        RETURNING key
                        """,
                        (
                            json.dumps(dict(value), default=str),
                            key,
                            str(expected_revision),
                            not_before,
                            expires_at,
                        ),
                    )
                    if await cursor.fetchone() is None:
                        return False
                    if not await _insert_state(conn, insert_key, insert_value):
                        raise _RollbackTransactionError()
                    await self._append_audit_in_transaction(conn, dict(audit_entry))
        except _RollbackTransactionError:
            return False
        return True

    async def compare_and_set_state_pair_with_audit_before(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        second_key: str,
        second_value: Mapping[str, Any],
        expected_second_revision: int,
        not_before: datetime,
        expires_at: datetime,
        insert_key: str | None = None,
        insert_value: Mapping[str, Any] | None = None,
        guard_key: str | None = None,
        guard_value: Mapping[str, Any] | None = None,
        expected_guard_revision: int | None = None,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        guard_supplied = (
            guard_key is not None
            and guard_value is not None
            and expected_guard_revision is not None
        )
        if (
            expected_revision < 1
            or expected_second_revision < 0
            or (insert_key is None) != (insert_value is None)
            or any(value is not None for value in (guard_key, guard_value, expected_guard_revision))
            is not guard_supplied
        ):
            raise ValueError("state pair expected revisions are invalid")
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    cursor = await conn.execute(
                        """
                        UPDATE state_kv
                           SET value = %s::jsonb,
                               updated_at = clock_timestamp()
                         WHERE key = %s
                           AND COALESCE(value ->> 'revision', '0') = %s
                           AND %s <= clock_timestamp()
                           AND clock_timestamp() < %s
                        RETURNING key
                        """,
                        (
                            json.dumps(dict(value), default=str),
                            key,
                            str(expected_revision),
                            not_before,
                            expires_at,
                        ),
                    )
                    if await cursor.fetchone() is None:
                        return False
                    if expected_second_revision == 0:
                        second_changed = await _insert_state(conn, second_key, second_value)
                    else:
                        second_changed = await _update_state_revision(
                            conn,
                            second_key,
                            second_value,
                            expected_second_revision,
                        )
                    if not second_changed:
                        raise _RollbackTransactionError()
                    if guard_supplied:
                        if (
                            guard_key is None
                            or guard_value is None
                            or expected_guard_revision is None
                        ):
                            raise ValueError("state pair guard is incomplete")
                        if not await _update_state_revision(
                            conn,
                            guard_key,
                            guard_value,
                            expected_guard_revision,
                        ):
                            raise _RollbackTransactionError()
                    if (
                        insert_key is not None
                        and insert_value is not None
                        and not await _insert_state(conn, insert_key, insert_value)
                    ):
                        raise _RollbackTransactionError()
                    await self._append_audit_in_transaction(conn, dict(audit_entry))
        except _RollbackTransactionError:
            return False
        return True

    async def advance_state_with_epoch(
        self: Any,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        epoch_key: str,
        epoch_value: Mapping[str, Any],
        expected_epoch_revision: int,
        forbidden_keys: tuple[str, ...],
    ) -> bool:
        if expected_revision < 0 or expected_epoch_revision < 1:
            raise ValueError("state epoch expected revisions are invalid")
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    await self._set_statement_timeout(conn)
                    if forbidden_keys:
                        cursor = await conn.execute(
                            "SELECT 1 FROM state_kv WHERE key = ANY(%s) LIMIT 1",
                            (list(forbidden_keys),),
                        )
                        if await cursor.fetchone() is not None:
                            return False
                    if expected_revision == 0:
                        changed = await _insert_state(conn, key, value)
                    else:
                        changed = await _update_state_revision(
                            conn,
                            key,
                            value,
                            expected_revision,
                        )
                    if not changed or not await _update_state_revision(
                        conn,
                        epoch_key,
                        epoch_value,
                        expected_epoch_revision,
                    ):
                        raise _RollbackTransactionError()
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


async def _write_state_revision(
    conn: Any,
    key: str,
    value: Mapping[str, Any],
    expected_revision: int,
) -> bool:
    if expected_revision == 0:
        return await _insert_state(conn, key, value)
    return await _update_state_revision(conn, key, value, expected_revision)


async def _upsert_state_when_field_matches(
    conn: Any,
    key: str,
    value: Mapping[str, Any],
    *,
    field: str,
) -> bool:
    cursor = await conn.execute(
        """
        INSERT INTO state_kv (key, value)
        VALUES (%s, %s::jsonb)
        ON CONFLICT (key) DO UPDATE
           SET value = EXCLUDED.value,
               updated_at = NOW()
         WHERE state_kv.value ->> %s = EXCLUDED.value ->> %s
        RETURNING key
        """,
        (key, json.dumps(dict(value), default=str), field, field),
    )
    return await cursor.fetchone() is not None
