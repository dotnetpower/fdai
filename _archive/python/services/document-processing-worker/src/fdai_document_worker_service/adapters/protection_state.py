"""PostgreSQL state for restart-safe protection reconciliation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentVersion,
    ProtectionState,
)
from psycopg.rows import dict_row

from fdai_document_worker_service.adapters.protection import (
    ProtectionReconciliationCandidate,
    ProtectionReconciliationDecision,
)
from fdai_document_worker_service.protection_reconciliation import (
    ClaimedProtectionCandidate,
)


class PostgresProtectionReconciliationStore:
    """Fence provider checks and invalidate revoked derivatives atomically."""

    def __init__(self, *, dsn: str, statement_timeout_ms: int = 15_000) -> None:
        if not dsn:
            raise ValueError("protection reconciliation DSN MUST NOT be empty")
        if statement_timeout_ms < 1:
            raise ValueError("protection reconciliation timeout MUST be positive")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms

    async def claim_due(
        self, *, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]:
        return await self._claim(
            status="active", owner=owner, limit=limit, lease_seconds=lease_seconds
        )

    async def claim_cleanup(
        self, *, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]:
        return await self._claim(
            status="cleanup_pending",
            owner=owner,
            limit=limit,
            lease_seconds=lease_seconds,
        )

    async def apply_decisions(
        self,
        claims: Sequence[ClaimedProtectionCandidate],
        decisions: Sequence[ProtectionReconciliationDecision],
        *,
        next_check_at: datetime,
    ) -> None:
        if len(claims) != len(decisions):
            raise DocumentLifecycleConflictError("protection reconciliation decision count changed")
        decisions_by_key = {
            (decision.document_id, decision.version_id): decision for decision in decisions
        }
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            for claim in claims:
                candidate = claim.candidate
                key = (candidate.document_id, candidate.version_id)
                decision = decisions_by_key.pop(key, None)
                if decision is None:
                    raise DocumentLifecycleConflictError(
                        "protection reconciliation decision identity changed"
                    )
                row = await self._locked_row(connection, claim)
                if (
                    row["source_sha256"] != decision.source_sha256
                    or int(row["policy_revision"]) > decision.policy_revision
                ):
                    raise DocumentLifecycleConflictError(
                        "protection reconciliation decision binding changed"
                    )
                if decision.revoked:
                    await self._invalidate_revoked(connection, claim, decision)
                else:
                    await connection.execute(
                        "UPDATE document_protection_reconciliation "
                        "SET policy_revision = %s, protection_state = %s, "
                        "next_check_at = %s, claim_owner = NULL, lease_expires_at = NULL, "
                        "revision = revision + 1, last_checked_at = NOW(), reason_code = %s "
                        "WHERE document_id = %s AND version_id = %s",
                        (
                            decision.policy_revision,
                            decision.state.value,
                            next_check_at,
                            decision.reason_code,
                            candidate.document_id,
                            candidate.version_id,
                        ),
                    )
            if decisions_by_key:
                raise DocumentLifecycleConflictError(
                    "protection reconciliation returned an unknown decision"
                )

    async def complete_cleanup(self, claim: ClaimedProtectionCandidate) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._locked_row(connection, claim)
            updated = await connection.execute(
                "UPDATE document_protection_reconciliation "
                "SET status = 'revoked', claim_owner = NULL, lease_expires_at = NULL, "
                "revision = revision + 1, last_checked_at = NOW() "
                "WHERE document_id = %s AND version_id = %s "
                "AND status = 'cleanup_pending' RETURNING version_id",
                (claim.candidate.document_id, claim.candidate.version_id),
            )
            if await updated.fetchone() is None:
                raise DocumentLifecycleConflictError(
                    "protection cleanup no longer matches pending state"
                )

    async def _claim(
        self, *, status: str, owner: str, limit: int, lease_seconds: int
    ) -> tuple[ClaimedProtectionCandidate, ...]:
        if not owner or not 1 <= limit <= 1000 or not 3 <= lease_seconds <= 3600:
            raise ValueError("protection reconciliation claim limits are invalid")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH due AS ("
                " SELECT document_id, version_id FROM document_protection_reconciliation"
                " WHERE status = %s AND next_check_at <= NOW()"
                " AND (lease_expires_at IS NULL OR lease_expires_at <= NOW())"
                " ORDER BY next_check_at, document_id, version_id"
                " FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE document_protection_reconciliation AS target"
                " SET claim_owner = %s, lease_expires_at = NOW() + (%s * INTERVAL '1 second'),"
                " revision = target.revision + 1"
                " FROM due WHERE target.document_id = due.document_id"
                " AND target.version_id = due.version_id"
                " RETURNING target.*",
                (status, limit, owner, lease_seconds),
            )
            rows = await cursor.fetchall()
        return tuple(_claimed(row) for row in rows)

    async def _locked_row(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        claim: ClaimedProtectionCandidate,
    ) -> dict[str, Any]:
        row = await (
            await connection.execute(
                "SELECT * FROM document_protection_reconciliation "
                "WHERE document_id = %s AND version_id = %s FOR UPDATE",
                (claim.candidate.document_id, claim.candidate.version_id),
            )
        ).fetchone()
        if (
            row is None
            or row["claim_owner"] != claim.claim_owner
            or int(row["revision"]) != claim.claim_revision
            or row["provider_ref"] != claim.candidate.provider_ref
            or row["source_sha256"] != claim.candidate.source_sha256
        ):
            raise DocumentLifecycleConflictError("protection reconciliation claim conflict")
        return row

    async def _invalidate_revoked(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        claim: ClaimedProtectionCandidate,
        decision: ProtectionReconciliationDecision,
    ) -> None:
        candidate = claim.candidate
        version_row = await (
            await connection.execute(
                "SELECT payload FROM document_version "
                "WHERE document_id = %s AND version_id = %s FOR UPDATE",
                (candidate.document_id, candidate.version_id),
            )
        ).fetchone()
        if version_row is None:
            raise DocumentLifecycleConflictError(
                "protection reconciliation document version disappeared"
            )
        version = DocumentVersion.model_validate(version_row["payload"])
        if (
            version.source_sha256 != candidate.source_sha256
            or version.protection_provider_ref != candidate.provider_ref
            or version.protection_policy_revision is None
            or version.protection_policy_revision > decision.policy_revision
        ):
            raise DocumentLifecycleConflictError(
                "protection reconciliation version binding changed"
            )
        revoked = version.model_copy(
            update={
                "active": False,
                "available": False,
                "protection_state": ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED,
                "protection_policy_revision": decision.policy_revision,
                "failure_code": decision.reason_code or "rights_management_revoked",
                "updated_at": datetime.now(tz=version.updated_at.tzinfo),
                "revision": version.revision + 1,
            }
        )
        updated = await connection.execute(
            "UPDATE document_version SET active = FALSE, revision = %s, "
            "payload = %s::jsonb, updated_at = %s "
            "WHERE document_id = %s AND version_id = %s AND revision = %s "
            "RETURNING version_id",
            (
                revoked.revision,
                revoked.model_dump_json(),
                revoked.updated_at,
                revoked.document_id,
                revoked.version_id,
                version.revision,
            ),
        )
        if await updated.fetchone() is None:
            raise DocumentLifecycleConflictError("protection reconciliation version CAS conflict")
        await connection.execute(
            "DELETE FROM knowledge_chunk "
            "WHERE metadata->>'document_id' = %s AND metadata->>'version_id' = %s",
            (str(candidate.document_id), str(candidate.version_id)),
        )
        event = _revocation_event(revoked)
        await connection.execute(
            "INSERT INTO document_worker_outbox "
            "(event_id, idempotency_key, topic, partition_key, payload, created_at) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s) "
            "ON CONFLICT (idempotency_key) DO NOTHING",
            (
                event.event_id,
                event.idempotency_key,
                event.topic,
                event.key,
                event.model_dump_json(),
                event.created_at,
            ),
        )
        await connection.execute(
            "UPDATE document_protection_reconciliation "
            "SET status = 'cleanup_pending', policy_revision = %s, "
            "protection_state = %s, next_check_at = NOW(), claim_owner = NULL, "
            "lease_expires_at = NULL, revision = revision + 1, "
            "last_checked_at = NOW(), reason_code = %s "
            "WHERE document_id = %s AND version_id = %s",
            (
                decision.policy_revision,
                ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED.value,
                decision.reason_code or "rights_management_revoked",
                candidate.document_id,
                candidate.version_id,
            ),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)

    async def _timeout(self, connection: psycopg.AsyncConnection[dict[str, Any]]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._statement_timeout_ms),),
        )


def _claimed(row: dict[str, Any]) -> ClaimedProtectionCandidate:
    return ClaimedProtectionCandidate(
        candidate=ProtectionReconciliationCandidate(
            document_id=UUID(str(row["document_id"])),
            version_id=UUID(str(row["version_id"])),
            source_sha256=str(row["source_sha256"]),
            provider_ref=str(row["provider_ref"]),
            policy_revision=int(row["policy_revision"]),
        ),
        upload_id=UUID(str(row["upload_id"])),
        claim_owner=str(row["claim_owner"]),
        claim_revision=int(row["revision"]),
    )


def _revocation_event(version: DocumentVersion) -> DocumentLifecycleEvent:
    identity = f"document.access_revoked:{version.version_id}:{version.protection_policy_revision}"
    event_id = UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16])
    return DocumentLifecycleEvent(
        event_id=event_id,
        idempotency_key=identity,
        topic="object.event",
        key=str(version.document_id),
        payload={
            "producer_principal": "Heimdall",
            "kind": "document_ingestion",
            "action": "document.access_revoked",
            "event_type": "document.access_revoked",
            "correlation_id": str(version.upload_id),
            "idempotency_key": identity,
            "resource_id": str(version.document_id),
            "resource_type": "document",
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "protection_state": version.protection_state.value,
        },
        created_at=version.updated_at,
    )
