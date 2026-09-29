"""Verifier-role readers over the fixed-parameter test-context source functions.

Each read runs under the verifier's own database role, which holds EXECUTE on four SECURITY
DEFINER functions and no SELECT on any source view or table. A function filters inside the
definer's context before it returns rows, so the verifier sees only the exact rows its lookup
names and can neither attach its own predicate nor read planner estimates for other keys.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import psycopg
from fdai_service_contracts.operational_evidence import OperationalEvidenceSourceHealth

from fdai.core.operational_context.test_context_lifecycle import context_history_key
from fdai.core.operational_evidence.readback.case_history_read import (
    AUTHENTICATION_SOURCE,
    SemanticAuthenticationReceiptRow,
)
from fdai.core.operational_evidence.readback.test_context_sources import (
    MAX_TARGET_COMMANDS,
    OPERATOR_OUTBOX_SOURCE,
    TEST_CONTEXT_STORE_SOURCE,
    AuditRow,
    OperatorCommandRow,
)
from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
    role_bound_connection,
)

MAX_AUDIT_DIGESTS = 256
TARGET_ROW_BOUND = MAX_TARGET_COMMANDS + 1
"""The commands-for-target function returns at most this many rows, one past the bound."""
AUDIT_ROW_BOUND = MAX_AUDIT_DIGESTS + 1
"""The transition-audit function returns at most this many rows, one past the bound."""
_PROBE_KEY = "fdai-readiness-probe"
_PROBE_HISTORY_KEY = "test-context-target:v1:" + "0" * 64
_PROBE_DIGEST = "sha256:" + "0" * 64
_PROBE_REQUEST_ID = "fdai-readiness-probe"
_HEALTH_FAILURES = (OSError, PermissionError, RuntimeError, ValueError, psycopg.Error)


class PostgresTestContextEvidenceSources:
    """Read Operator commands, Mimir history, and atomic audit rows through definer functions."""

    source_ids = (OPERATOR_OUTBOX_SOURCE, TEST_CONTEXT_STORE_SOURCE)

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
                    "FROM public.fdai_operational_evidence_commands_for_key(%s)",
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
                    "FROM public.fdai_operational_evidence_commands_for_target(%s, %s)",
                    (access_scope_digest, target_ref),
                )
            ).fetchall()
        return tuple(_command(row) for row in rows[:TARGET_ROW_BOUND])

    async def history(
        self, *, access_scope_digest: str, target_ref: str
    ) -> Mapping[str, Any] | None:
        """Return the revisioned history value for one exact scope and target."""

        async with role_bound_connection(self._config) as connection:
            row = await (
                await connection.execute(
                    "SELECT public.fdai_operational_evidence_context_history(%s) AS value",
                    (context_history_key(access_scope_digest, target_ref),),
                )
            ).fetchone()
        return row["value"] if row is not None else None

    async def transition_entries(self, *, context_digests: tuple[str, ...]) -> tuple[AuditRow, ...]:
        """Return the hash-chained audit rows that name any of the given revisions."""

        if not context_digests or len(context_digests) > MAX_AUDIT_DIGESTS:
            return ()
        async with role_bound_connection(self._config) as connection:
            rows = await (
                await connection.execute(
                    "SELECT seq, entry, previous_hash, entry_hash "
                    "FROM public.fdai_operational_evidence_transition_audit(%s)",
                    (list(context_digests),),
                )
            ).fetchall()
        return tuple(
            AuditRow(
                seq=int(row["seq"]),
                entry=row["entry"],
                previous_hash=str(row["previous_hash"]),
                entry_hash=str(row["entry_hash"]),
            )
            for row in rows[:AUDIT_ROW_BOUND]
        )

    async def source_health(self) -> dict[str, OperationalEvidenceSourceHealth]:
        """Run one bounded probe read per declared source under the verifier role.

        A probe proves only that the function executes for the verifier; it never reads a row
        the verifier could not already read, and any failure reports that source unavailable.
        """

        probes = {
            OPERATOR_OUTBOX_SOURCE: (
                "SELECT count(*) AS rows "
                "FROM public.fdai_operational_evidence_commands_for_key(%s)",
                (_PROBE_KEY,),
            ),
            TEST_CONTEXT_STORE_SOURCE: (
                "SELECT public.fdai_operational_evidence_context_history(%s) IS NULL AS absent, "
                "(SELECT count(*) FROM public.fdai_operational_evidence_transition_audit(%s)) "
                "AS rows",
                (_PROBE_HISTORY_KEY, [_PROBE_DIGEST]),
            ),
        }
        health: dict[str, OperationalEvidenceSourceHealth] = {}
        for source_id, (statement, parameters) in probes.items():
            try:
                async with role_bound_connection(self._config) as connection:
                    await (await connection.execute(statement, parameters)).fetchone()
            except _HEALTH_FAILURES:
                health[source_id] = OperationalEvidenceSourceHealth.UNAVAILABLE
            else:
                health[source_id] = OperationalEvidenceSourceHealth.HEALTHY
        return health


class PostgresSemanticAuthenticationReceiptSource:
    """Read semantic authentication receipts through the Operator-owned definer function."""

    source_ids = (AUTHENTICATION_SOURCE,)

    def __init__(self, config: PostgresOperationalEvidenceConfig) -> None:
        if config.expected_role != VERIFIER_ROLE:
            raise ValueError("semantic authentication source requires the verifier role")
        self._config = config

    async def receipts_for_request(
        self, receipt_digest: str, request_id: str
    ) -> tuple[SemanticAuthenticationReceiptRow, ...]:
        """Return the receipt retained for one exact request, one past the duplicate bound."""

        async with role_bound_connection(self._config) as connection:
            rows = await (
                await connection.execute(
                    "SELECT receipt_digest, request_id, principal_id, receipt, recorded_at "
                    "FROM public.fdai_operator_authentication_receipt_for_request(%s, %s)",
                    (receipt_digest, request_id),
                )
            ).fetchall()
        return tuple(
            SemanticAuthenticationReceiptRow(
                receipt_digest=str(row["receipt_digest"]),
                request_id=str(row["request_id"]),
                principal_id=str(row["principal_id"]),
                receipt=row["receipt"],
                recorded_at=row["recorded_at"],
            )
            for row in rows[:2]
        )

    async def source_health(self) -> dict[str, OperationalEvidenceSourceHealth]:
        """Probe the exact function without reading an existing receipt."""

        try:
            async with role_bound_connection(self._config) as connection:
                await (
                    await connection.execute(
                        "SELECT count(*) AS rows "
                        "FROM public.fdai_operator_authentication_receipt_for_request(%s, %s)",
                        (_PROBE_DIGEST, _PROBE_REQUEST_ID),
                    )
                ).fetchone()
        except _HEALTH_FAILURES:
            return {AUTHENTICATION_SOURCE: OperationalEvidenceSourceHealth.UNAVAILABLE}
        return {AUTHENTICATION_SOURCE: OperationalEvidenceSourceHealth.HEALTHY}


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


__all__ = [
    "AUDIT_ROW_BOUND",
    "MAX_AUDIT_DIGESTS",
    "TARGET_ROW_BOUND",
    "PostgresTestContextEvidenceSources",
    "PostgresSemanticAuthenticationReceiptSource",
    "operator_command_key",
]
