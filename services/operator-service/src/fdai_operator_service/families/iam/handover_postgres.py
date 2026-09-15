"""Bounded read-only PostgreSQL evidence and workload gates for handover."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

import psycopg
from fdai_operator_service.families.iam.errors import IamUnavailableError


@dataclass(frozen=True, slots=True)
class PostgresHandoverActivityGuard:
    """Suppress invitations while any incident or human approval is active."""

    dsn: str
    connect_timeout_s: int = 10
    statement_timeout_ms: int = 10_000

    async def may_invite(self) -> bool:
        try:
            async with await psycopg.AsyncConnection.connect(
                self.dsn, connect_timeout=self.connect_timeout_s
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{self.statement_timeout_ms}ms",),
                )
                row = await (
                    await connection.execute(
                        """
                        SELECT
                            EXISTS (
                                SELECT 1 FROM operator_incident_projection
                                 WHERE valid_to_seq IS NULL AND has_incident_activity
                                   AND LOWER(projected_state) NOT IN (
                                       'closed', 'resolved', 'mitigated'
                                   )
                            ) AS incident_busy,
                            EXISTS (
                                SELECT 1 FROM state_kv
                                 WHERE key LIKE 'hil_park:%'
                                   AND value ->> 'status' = 'pending'
                            ) AS approval_busy
                        """
                    )
                ).fetchone()
        except psycopg.Error:
            return False
        return row is not None and row[0] is False and row[1] is False


@runtime_checkable
class HandoverReviewerEvidenceVerifier(Protocol):
    """Check document ACL against current server-resolved reviewer roles and group membership."""

    async def verify_review(
        self,
        *,
        principal_id: str,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
        reviewer_id: str,
        reviewer_roles: tuple[str, ...],
        reviewer_group_ids: tuple[str, ...],
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class PostgresHandoverEvidenceVerifier:
    """Read only the exact uploaded version through its restricted SQL function."""

    dsn: str
    connect_timeout_s: int = 10
    statement_timeout_ms: int = 10_000

    async def verify(
        self,
        *,
        principal_id: str,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
    ) -> bool:
        """Require the exact governed, live, indexed source; a missing migration is unavailable."""
        return await self._verify(
            "SELECT fdai_verify_handover_document_admission(%s, %s, %s, %s)",
            (principal_id, document_id, version_id, source_sha256),
        )

    async def verify_review(
        self,
        *,
        principal_id: str,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
        reviewer_id: str,
        reviewer_roles: tuple[str, ...],
        reviewer_group_ids: tuple[str, ...],
    ) -> bool:
        """Use current directory evidence, never groups from duty, token, or goal records."""
        return await self._verify(
            "SELECT fdai_verify_handover_document_review(%s, %s, %s, %s, %s, %s, %s)",
            (
                principal_id,
                document_id,
                version_id,
                source_sha256,
                reviewer_id,
                list(reviewer_roles),
                list(reviewer_group_ids),
            ),
        )

    async def _verify(self, query: str, parameters: tuple[object, ...]) -> bool:
        if not self.dsn:
            raise IamUnavailableError("handover evidence verifier is not configured")
        try:
            async with await psycopg.AsyncConnection.connect(
                self.dsn, connect_timeout=self.connect_timeout_s
            ) as connection:
                await connection.set_read_only(True)
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{self.statement_timeout_ms}ms",),
                )
                role = await (await connection.execute("SELECT current_user")).fetchone()
                if role is None or role[0] != "fdai_operator":
                    raise IamUnavailableError(
                        "handover evidence reader requires the Operator SQL role"
                    )
                row = await (await connection.execute(query, parameters)).fetchone()
        except psycopg.Error as exc:
            raise IamUnavailableError("authoritative document metadata is unavailable") from exc
        return row is not None and row[0] is True


__all__ = [
    "HandoverReviewerEvidenceVerifier",
    "PostgresHandoverActivityGuard",
    "PostgresHandoverEvidenceVerifier",
]
