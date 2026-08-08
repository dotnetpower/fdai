"""PostgreSQL document metadata and durable worker-claim adapter."""

# ruff: noqa: S608 - SQL fragments are private fixed literals.

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentNotFoundError,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    UploadSession,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)
from psycopg.rows import dict_row

_CLAIM_COLUMNS = (
    "upload_id, stage, owner, attempt_id, revision, status, claimed_at, "
    "lease_expires_at, finished_at"
)


@dataclass(frozen=True, slots=True)
class PostgresWorkerConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("Postgres worker DSN MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("Postgres worker timeouts MUST be positive")


class PostgresDocumentMetadataStore:
    """Persist worker-owned lifecycle and revision-fenced claim transitions."""

    def __init__(self, *, config: PostgresWorkerConfig) -> None:
        self._config: Final = config

    def readiness(self) -> AdapterReadiness:
        """Report validated DSN/timeouts without opening a database connection."""
        return configured_readiness("postgres-document-metadata")

    async def probe_readiness(self) -> AdapterReadiness:
        """Run one bounded read-only database statement."""
        adapter = "postgres-document-metadata"
        try:
            async with asyncio.timeout(min(float(self._config.connect_timeout_s), 5.0)):
                async with await self._connect() as connection:
                    await connection.execute("SELECT 1")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def create(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        event: DocumentLifecycleEvent | None = None,
    ) -> None:
        raise PermissionError("the worker database role cannot create uploads")

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        row = await self._one(
            "SELECT payload FROM document_upload_session WHERE upload_id = %s",
            (upload_id,),
        )
        if row is None:
            raise DocumentNotFoundError("upload was not found")
        return UploadSession.model_validate(_payload(row["payload"]))

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        row = await self._one(
            "SELECT payload FROM document_version WHERE document_id = %s AND version_id = %s",
            (document_id, version_id),
        )
        if row is None:
            raise DocumentNotFoundError("document version was not found")
        return DocumentVersion.model_validate(_payload(row["payload"]))

    async def transition(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        expected_upload_state: str,
        expected_upload_revision: int,
        expected_version_state: str,
        expected_version_revision: int,
        event: DocumentLifecycleEvent,
    ) -> None:
        """Reject worker lifecycle writes that are not bound to a stage claim."""
        raise PermissionError("worker lifecycle transitions require an active stage claim")

    async def transition_worker_stage(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        claim: DocumentWorkerClaim,
        expected_upload_state: str,
        expected_upload_revision: int,
        expected_version_state: str,
        expected_version_revision: int,
        event: DocumentLifecycleEvent,
    ) -> None:
        """Fence lifecycle and outbox commit with the active unexpired claim."""
        if session.revision != expected_upload_revision + 1:
            raise ValueError("upload transition revision MUST increment exactly once")
        if version.revision != expected_version_revision + 1:
            raise ValueError("version transition revision MUST increment exactly once")
        if claim.upload_id != session.upload_id:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._lock_active_claim(connection, claim)
            upload_cursor = await connection.execute(
                "UPDATE document_upload_session SET state = %s, revision = %s, "
                "payload = %s::jsonb, updated_at = NOW() WHERE upload_id = %s "
                "AND state = %s AND revision = %s RETURNING upload_id",
                (
                    session.state.value,
                    session.revision,
                    session.model_dump_json(),
                    session.upload_id,
                    expected_upload_state,
                    expected_upload_revision,
                ),
            )
            if await upload_cursor.fetchone() is None:
                raise DocumentLifecycleConflictError("upload lifecycle CAS conflict")
            if version.active:
                await connection.execute(
                    "UPDATE document_version SET active = FALSE, revision = revision + 1, "
                    "payload = jsonb_set(jsonb_set(payload, '{active}', 'false'::jsonb), "
                    "'{revision}', to_jsonb(revision + 1)), "
                    "updated_at = NOW() WHERE document_id = %s AND version_id <> %s AND active",
                    (version.document_id, version.version_id),
                )
            version_cursor = await connection.execute(
                "UPDATE document_version SET state = %s, active = %s, revision = %s, "
                "payload = %s::jsonb, updated_at = %s WHERE document_id = %s "
                "AND version_id = %s AND state = %s AND revision = %s RETURNING version_id",
                (
                    version.state.value,
                    version.active,
                    version.revision,
                    version.model_dump_json(),
                    version.updated_at,
                    version.document_id,
                    version.version_id,
                    expected_version_state,
                    expected_version_revision,
                ),
            )
            if await version_cursor.fetchone() is None:
                raise DocumentLifecycleConflictError("document version lifecycle CAS conflict")
            await _enqueue_outbox(connection, event)

    async def assert_worker_stage_active(self, claim: DocumentWorkerClaim) -> None:
        """Revalidate a claim immediately before a non-transactional stage effect."""
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._lock_active_claim(connection, claim)

    async def enqueue_worker_event(
        self, event: DocumentLifecycleEvent, *, claim: DocumentWorkerClaim
    ) -> None:
        """Fence a non-replay outbox write with the active worker claim."""
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._lock_active_claim(connection, claim)
            await _enqueue_outbox(connection, event)

    async def enqueue_event(self, event: DocumentLifecycleEvent) -> None:
        """Persist one replay fact outside a lifecycle transition."""
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await _enqueue_outbox(connection, event)

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        rows = await self._many(
            "SELECT payload FROM document_version WHERE document_id = %s "
            "ORDER BY created_at ASC, version_id ASC",
            (document_id,),
        )
        if not rows:
            raise DocumentNotFoundError("document was not found")
        return tuple(DocumentVersion.model_validate(_payload(row["payload"])) for row in rows)

    async def list_uploads_by_state(self, state: str, *, limit: int) -> tuple[UploadSession, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("document upload state limit MUST be in [1, 1000]")
        rows = await self._many(
            "SELECT payload FROM document_upload_session WHERE state = %s "
            "ORDER BY created_at ASC, upload_id ASC LIMIT %s",
            (state, limit),
        )
        return tuple(UploadSession.model_validate(_payload(row["payload"])) for row in rows)

    async def claim_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        lease_seconds: int,
    ) -> DocumentWorkerClaim | None:
        _validate_claim(owner, lease_seconds)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO document_worker_claim ("
                f"{_CLAIM_COLUMNS}) VALUES ("
                "%s, %s, %s, %s, 1, 'active', clock_timestamp(), "
                "clock_timestamp() + (%s * INTERVAL '1 second'), NULL) "
                "ON CONFLICT (upload_id, stage) DO NOTHING "
                f"RETURNING {_CLAIM_COLUMNS}",
                (upload_id, stage.value, owner, attempt_id, lease_seconds),
            )
            row = await cursor.fetchone()
            if row is not None:
                return _claim(row)
            current_row = await (
                await connection.execute(
                    f"SELECT {_CLAIM_COLUMNS}, clock_timestamp() AS server_now "
                    "FROM document_worker_claim WHERE upload_id = %s AND stage = %s FOR UPDATE",
                    (upload_id, stage.value),
                )
            ).fetchone()
            if current_row is None:
                raise RuntimeError("document worker claim disappeared during acquisition")
            current = _claim(current_row)
            server_now = current_row["server_now"]
            if current.status is DocumentWorkerClaimStatus.COMPLETED:
                return None
            if current.status is DocumentWorkerClaimStatus.ACTIVE:
                if (
                    current.owner == owner
                    and current.attempt_id == attempt_id
                    and current.lease_expires_at > server_now
                ):
                    return current
                if current.lease_expires_at > server_now or current.attempt_id == attempt_id:
                    return None
            if current.attempt_id == attempt_id:
                return None
            reclaimed = await (
                await connection.execute(
                    "UPDATE document_worker_claim SET owner = %s, attempt_id = %s, "
                    "revision = revision + 1, status = 'active', claimed_at = clock_timestamp(), "
                    "lease_expires_at = clock_timestamp() + (%s * INTERVAL '1 second'), "
                    "finished_at = NULL WHERE upload_id = %s AND stage = %s AND revision = %s "
                    f"RETURNING {_CLAIM_COLUMNS}",
                    (
                        owner,
                        attempt_id,
                        lease_seconds,
                        upload_id,
                        stage.value,
                        current.revision,
                    ),
                )
            ).fetchone()
            if reclaimed is None:
                raise DocumentWorkerClaimConflictError("document worker claim conflict")
            return _claim(reclaimed)

    async def renew_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        lease_seconds: int,
    ) -> DocumentWorkerClaim:
        _validate_claim(owner, lease_seconds)
        return await self._update_claim(
            upload_id,
            stage,
            owner,
            attempt_id,
            expected_revision,
            "revision = revision + 1, lease_expires_at = "
            "clock_timestamp() + (%s * INTERVAL '1 second')",
            (lease_seconds,),
        )

    async def complete_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim:
        return await self._finish_claim(
            upload_id,
            stage,
            owner,
            attempt_id,
            expected_revision,
            DocumentWorkerClaimStatus.COMPLETED,
        )

    async def release_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim:
        return await self._finish_claim(
            upload_id,
            stage,
            owner,
            attempt_id,
            expected_revision,
            DocumentWorkerClaimStatus.RELEASED,
        )

    async def _finish_claim(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        status: DocumentWorkerClaimStatus,
    ) -> DocumentWorkerClaim:
        try:
            return await self._update_claim(
                upload_id,
                stage,
                owner,
                attempt_id,
                expected_revision,
                "revision = revision + 1, status = %s, finished_at = clock_timestamp()",
                (status.value,),
            )
        except DocumentWorkerClaimConflictError:
            row = await self._one(
                f"SELECT {_CLAIM_COLUMNS} FROM document_worker_claim "
                "WHERE upload_id = %s AND stage = %s",
                (upload_id, stage.value),
            )
            if row is not None:
                current = _claim(row)
                if (
                    current.status is status
                    and current.owner == owner
                    and current.attempt_id == attempt_id
                    and current.revision == expected_revision + 1
                ):
                    return current
            raise

    async def _update_claim(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        assignment: str,
        assignment_params: tuple[object, ...],
    ) -> DocumentWorkerClaim:
        if not owner or expected_revision < 1:
            raise ValueError("document worker owner and revision MUST be valid")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            row = await (
                await connection.execute(
                    f"UPDATE document_worker_claim SET {assignment} "
                    "WHERE upload_id = %s AND stage = %s AND owner = %s AND attempt_id = %s "
                    "AND revision = %s AND status = 'active' "
                    "AND lease_expires_at > clock_timestamp() "
                    f"RETURNING {_CLAIM_COLUMNS}",
                    (
                        *assignment_params,
                        upload_id,
                        stage.value,
                        owner,
                        attempt_id,
                        expected_revision,
                    ),
                )
            ).fetchone()
        if row is None:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        return _claim(row)

    @staticmethod
    async def _lock_active_claim(
        connection: psycopg.AsyncConnection[Any], claim: DocumentWorkerClaim
    ) -> None:
        row = await (
            await connection.execute(
                "SELECT 1 FROM document_worker_claim WHERE upload_id = %s AND stage = %s "
                "AND owner = %s AND attempt_id = %s AND revision = %s AND status = 'active' "
                "AND lease_expires_at > clock_timestamp() FOR UPDATE",
                (
                    claim.upload_id,
                    claim.stage.value,
                    claim.owner,
                    claim.attempt_id,
                    claim.revision,
                ),
            )
        ).fetchone()
        if row is None:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")

    async def _one(self, query: str, params: tuple[object, ...]) -> dict[str, Any] | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await (await connection.execute(query, params)).fetchone()

    async def _many(self, query: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await (await connection.execute(query, params)).fetchall()

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("document metadata payload is not a JSON object")


def _claim(row: dict[str, Any]) -> DocumentWorkerClaim:
    return DocumentWorkerClaim(
        upload_id=row["upload_id"],
        stage=DocumentWorkerStage(row["stage"]),
        owner=str(row["owner"]),
        attempt_id=row["attempt_id"],
        revision=int(row["revision"]),
        status=DocumentWorkerClaimStatus(row["status"]),
        claimed_at=row["claimed_at"],
        lease_expires_at=row["lease_expires_at"],
        finished_at=row["finished_at"],
    )


def _validate_claim(owner: str, lease_seconds: int) -> None:
    if not owner or len(owner) > 256 or lease_seconds < 1 or lease_seconds > 3600:
        raise ValueError("document worker owner and lease MUST be valid")


async def _enqueue_outbox(
    connection: psycopg.AsyncConnection[Any], event: DocumentLifecycleEvent
) -> None:
    await connection.execute(
        "INSERT INTO document_worker_outbox "
        "(event_id, idempotency_key, topic, partition_key, payload, created_at) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s) ON CONFLICT (idempotency_key) DO NOTHING",
        (
            event.event_id,
            event.idempotency_key,
            event.topic,
            event.key,
            event.model_dump_json(),
            event.created_at,
        ),
    )
