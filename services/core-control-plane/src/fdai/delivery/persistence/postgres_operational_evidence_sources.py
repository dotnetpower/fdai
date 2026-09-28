"""Verifier-role readers over the least-privilege test-context source views.

Each read runs under the verifier's own database role, which holds SELECT on the views alone and
no write privilege on any source table. Rows come from ``state_kv`` and ``audit_log`` only as the
views expose them, so the verifier never sees another row family.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from fdai.core.operational_context.test_context_lifecycle import context_history_key
from fdai.core.operational_evidence.readback.test_context_sources import (
    MAX_TARGET_COMMANDS,
    AuditRow,
    OperatorCommandRow,
)
from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
    role_bound_connection,
)

_MAX_AUDIT_ROWS = 256


class PostgresTestContextEvidenceSources:
    """Read Operator commands, Mimir history, and atomic audit rows through verifier views."""

    def __init__(self, config: PostgresOperationalEvidenceConfig) -> None:
        if config.expected_role != VERIFIER_ROLE:
            raise ValueError("test-context evidence sources require the verifier role")
        self._config = config

    async def commands_for_key(self, idempotency_key: str) -> tuple[OperatorCommandRow, ...]:
        """Return at most two rows so a competing record for one key is detectable."""

        if not idempotency_key.strip() or len(idempotency_key) > 256:
            return ()
        async with role_bound_connection(self._config) as connection:
            rows = await (
                await connection.execute(
                    "SELECT key, record, dispatch_status, authentication_receipt "
                    "FROM public.operational_evidence_test_context_command "
                    "WHERE record ->> 'idempotency_key' = %s ORDER BY key LIMIT 2",
                    (idempotency_key,),
                )
            ).fetchall()
        return tuple(_command(row) for row in rows)

    async def commands_for_target(
        self, *, access_scope_digest: str, target_ref: str
    ) -> tuple[OperatorCommandRow, ...]:
        """Return every command row for one scope and target, one past the bound."""

        async with role_bound_connection(self._config) as connection:
            rows = await (
                await connection.execute(
                    "SELECT key, record, dispatch_status, authentication_receipt "
                    "FROM public.operational_evidence_test_context_command "
                    "WHERE access_scope_digest = %s AND target_ref = %s ORDER BY key LIMIT %s",
                    (access_scope_digest, target_ref, MAX_TARGET_COMMANDS + 1),
                )
            ).fetchall()
        return tuple(_command(row) for row in rows)

    async def history(
        self, *, access_scope_digest: str, target_ref: str
    ) -> Mapping[str, Any] | None:
        """Return the revisioned history value for one exact scope and target."""

        async with role_bound_connection(self._config) as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM public.operational_evidence_test_context_history "
                    "WHERE key = %s",
                    (context_history_key(access_scope_digest, target_ref),),
                )
            ).fetchone()
        return row["value"] if row is not None else None

    async def transition_entries(self, *, context_digests: tuple[str, ...]) -> tuple[AuditRow, ...]:
        """Return the hash-chained audit rows that name any of the given revisions."""

        if not context_digests or len(context_digests) > _MAX_AUDIT_ROWS:
            return ()
        async with role_bound_connection(self._config) as connection:
            rows = await (
                await connection.execute(
                    "SELECT seq, entry, previous_hash, entry_hash "
                    "FROM public.operational_evidence_test_context_audit "
                    "WHERE entry ->> 'context_digest' = ANY(%s) ORDER BY seq LIMIT %s",
                    (list(context_digests), _MAX_AUDIT_ROWS + 1),
                )
            ).fetchall()
        return tuple(
            AuditRow(
                seq=int(row["seq"]),
                entry=row["entry"],
                previous_hash=str(row["previous_hash"]),
                entry_hash=str(row["entry_hash"]),
            )
            for row in rows
        )


def operator_command_key(idempotency_key: str) -> str:
    """Return the Operator outbox key that one conversation idempotency key addresses."""

    return "operator-proposal:conversation:" + hashlib.sha256(idempotency_key.encode()).hexdigest()


def _command(row: Mapping[str, Any]) -> OperatorCommandRow:
    receipt = row.get("authentication_receipt")
    return OperatorCommandRow(
        key=str(row["key"]),
        record=row["record"],
        dispatch_status=str(row.get("dispatch_status") or ""),
        authentication_receipt=receipt if isinstance(receipt, dict) else None,
    )


__all__ = ["PostgresTestContextEvidenceSources", "operator_command_key"]
