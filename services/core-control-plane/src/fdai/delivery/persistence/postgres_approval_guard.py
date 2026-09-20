"""Atomic PostgreSQL state transitions guarded by durable workflow approval."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

import psycopg

from fdai.shared.providers.state_store import workflow_approval_decisions_from_state

SetStatementTimeout = Callable[[psycopg.AsyncConnection[Any]], Awaitable[None]]
AppendAuditInTransaction = Callable[
    [psycopg.AsyncConnection[Any], Mapping[str, Any]],
    Awaitable[None],
]


async def compare_and_set_state_with_approval_guard(
    *,
    connection: psycopg.AsyncConnection[Any],
    set_statement_timeout: SetStatementTimeout,
    append_audit_in_transaction: AppendAuditInTransaction,
    key: str,
    value: Mapping[str, Any],
    expected_revision: int,
    approval_key: str,
    expected_approval_revision: int,
    expected_approval_process_id: str,
    expected_approval_step_id: str,
    expected_approval_attempt: int,
    expected_approval_requester: str,
    expected_approval_quorum: int,
    expected_no_self_approval: bool,
    expected_approval_decisions: tuple[tuple[str, str, str], ...],
    evaluated_at: datetime,
    admission_verified_at: datetime,
    admission_valid_until: datetime,
    audit_entry: Mapping[str, Any],
) -> bool:
    """Commit one state update only while exact approval and admission remain current."""

    if expected_revision < 0 or expected_approval_revision < 0:
        raise ValueError("guarded expected revisions MUST be >= 0")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("guarded CAS evaluation time MUST be timezone-aware")
    async with connection.transaction():
        await set_statement_timeout(connection)
        guard_cursor = await connection.execute(
            """
                SELECT value
                  FROM state_kv
                 WHERE key = %s
                   AND COALESCE(value ->> 'revision', '0') = %s
                   AND value ->> 'state' = 'pending'
                 FOR UPDATE
                """,
            (approval_key, str(expected_approval_revision)),
        )
        guard_row = await guard_cursor.fetchone()
        if guard_row is None:
            return False
        guard_record = guard_row["value"]
        if (
            not isinstance(guard_record, Mapping)
            or workflow_approval_decisions_from_state(guard_record) != expected_approval_decisions
        ):
            return False
        cursor = await connection.execute(
            """
                UPDATE state_kv AS target
                   SET value = %s::jsonb,
                       updated_at = NOW()
                 WHERE target.key = %s
                   AND COALESCE(target.value ->> 'revision', '0') = %s
                   AND %s <= clock_timestamp()
                   AND %s > clock_timestamp()
                   AND EXISTS (
                       SELECT 1
                         FROM state_kv AS approval
                        WHERE approval.key = %s
                          AND COALESCE(approval.value ->> 'revision', '0') = %s
                          AND approval.value ->> 'state' = 'pending'
                          AND approval.value ->> 'process_id' = %s
                          AND approval.value ->> 'step_id' = %s
                          AND COALESCE(approval.value ->> 'attempt', '1') = %s
                          AND approval.value ->> 'requester_principal' = %s
                          AND approval.value ->> 'quorum' = %s
                          AND (approval.value ->> 'no_self_approval')::boolean = %s
                          AND (approval.value ->> 'requested_at')::timestamptz
                              <= clock_timestamp()
                          AND (approval.value ->> 'expires_at')::timestamptz
                              > clock_timestamp()
                   )
                RETURNING target.key
                """,
            (
                json.dumps(dict(value), default=str),
                key,
                str(expected_revision),
                admission_verified_at,
                admission_valid_until,
                approval_key,
                str(expected_approval_revision),
                expected_approval_process_id,
                expected_approval_step_id,
                str(expected_approval_attempt),
                expected_approval_requester,
                str(expected_approval_quorum),
                expected_no_self_approval,
            ),
        )
        if await cursor.fetchone() is None:
            return False
        await append_audit_in_transaction(connection, dict(audit_entry))
    return True


__all__ = ["compare_and_set_state_with_approval_guard"]
