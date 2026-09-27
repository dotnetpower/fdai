"""Atomic PostgreSQL transitions for Assurance Twin source confirmation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


class PostgresAssuranceTwinConfirmationMixin:
    """Focused atomic source/target transitions for PostgresStateStore."""

    async def confirm_assurance_twin_source(
        self,
        *,
        source_key: str,
        source_value: Mapping[str, Any],
        expected_source_revision: int,
        target_key: str,
        target_value: Mapping[str, Any],
        expected_target_revision: int,
        require_fresh: bool,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        return await confirm_source(
            self,
            source_key=source_key,
            source_value=source_value,
            expected_source_revision=expected_source_revision,
            target_key=target_key,
            target_value=target_value,
            expected_target_revision=expected_target_revision,
            require_fresh=require_fresh,
            audit_entry=audit_entry,
        )

    async def conflict_assurance_twin_source(
        self,
        *,
        source_key: str,
        source_value: Mapping[str, Any],
        expected_source_revision: int,
        target_key: str,
        target_value: Mapping[str, Any] | None,
        expected_target_revision: int | None,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        return await conflict_source(
            self,
            source_key=source_key,
            source_value=source_value,
            expected_source_revision=expected_source_revision,
            target_key=target_key,
            target_value=target_value,
            expected_target_revision=expected_target_revision,
            audit_entry=audit_entry,
        )


async def confirm_source(
    store: Any,
    *,
    source_key: str,
    source_value: Mapping[str, Any],
    expected_source_revision: int,
    target_key: str,
    target_value: Mapping[str, Any],
    expected_target_revision: int,
    require_fresh: bool,
    audit_entry: Mapping[str, Any],
) -> bool:
    async with store._connection() as connection:
        async with connection.transaction():
            await store._set_statement_timeout(connection)
            rows = await _locked_rows(connection, (source_key, target_key))
            source = rows.get(source_key)
            target = rows.get(target_key)
            if (
                not isinstance(source, Mapping)
                or not isinstance(target, Mapping)
                or source.get("revision", 0) != expected_source_revision
                or target.get("revision", 0) != expected_target_revision
                or (require_fresh and not _fresh(source))
            ):
                return False
            await _write(connection, source_key, source_value)
            await _write(connection, target_key, target_value)
            await store._append_audit_in_transaction(connection, dict(audit_entry))
    return True


async def conflict_source(
    store: Any,
    *,
    source_key: str,
    source_value: Mapping[str, Any],
    expected_source_revision: int,
    target_key: str,
    target_value: Mapping[str, Any] | None,
    expected_target_revision: int | None,
    audit_entry: Mapping[str, Any],
) -> bool:
    keys = (source_key,) if target_value is None else (source_key, target_key)
    async with store._connection() as connection:
        async with connection.transaction():
            await store._set_statement_timeout(connection)
            rows = await _locked_rows(connection, keys)
            source = rows.get(source_key)
            target = rows.get(target_key)
            if (
                not isinstance(source, Mapping)
                or source.get("revision", 0) != expected_source_revision
                or (
                    target_value is not None
                    and (
                        not isinstance(target, Mapping)
                        or expected_target_revision is None
                        or target.get("revision", 0) != expected_target_revision
                    )
                )
            ):
                return False
            await _write(connection, source_key, source_value)
            if target_value is not None:
                await _write(connection, target_key, target_value)
            await store._append_audit_in_transaction(connection, dict(audit_entry))
    return True


async def _locked_rows(connection: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    cursor = await connection.execute(
        """
        SELECT key, value
          FROM state_kv
         WHERE key = ANY(%s)
         FOR UPDATE
        """,
        (list(keys),),
    )
    return {str(row["key"]): row["value"] for row in await cursor.fetchall()}


async def _write(connection: Any, key: str, value: Mapping[str, Any]) -> None:
    await connection.execute(
        "UPDATE state_kv SET value=%s::jsonb, updated_at=NOW() WHERE key=%s",
        (json.dumps(dict(value), default=str), key),
    )


def _fresh(source: Mapping[str, Any]) -> bool:
    try:
        fresh_until = datetime.fromisoformat(str(source.get("fresh_until") or ""))
    except ValueError:
        return False
    return fresh_until.tzinfo is not None and fresh_until > datetime.now(UTC)


__all__ = ["PostgresAssuranceTwinConfirmationMixin", "confirm_source", "conflict_source"]
