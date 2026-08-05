"""PostgreSQL metadata store for durable document-ingestion state."""

# ruff: noqa: S608 - interpolated SQL fragments are module constants or private fixed literals.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.shared.contracts import (
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    UploadSession,
)
from fdai.shared.providers.document_ingestion import (
    DocumentNotFoundError,
    DocumentWorkerClaimConflictError,
)

_WORKER_CLAIM_COLUMNS = (
    "upload_id, stage, owner, attempt_id, revision, status, claimed_at, "
    "lease_expires_at, finished_at"
)


@dataclass(frozen=True, slots=True)
class PostgresDocumentMetadataStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresDocumentMetadataStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresDocumentMetadataStoreConfig timeouts MUST be positive")


class PostgresDocumentMetadataStore:
    def __init__(self, *, config: PostgresDocumentMetadataStoreConfig) -> None:
        self._config: Final = config

    async def create(self, session: UploadSession, version: DocumentVersion) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO document_upload_session "
                    "(upload_id, document_id, version_id, state, payload, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        session.upload_id,
                        session.document_id,
                        session.version_id,
                        session.state.value,
                        session.model_dump_json(),
                        session.created_at,
                        session.created_at,
                    ),
                )
                await connection.execute(
                    "INSERT INTO document_version "
                    "(document_id, version_id, upload_id, state, active, payload, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        version.document_id,
                        version.version_id,
                        version.upload_id,
                        version.state.value,
                        version.active,
                        version.model_dump_json(),
                        version.created_at,
                        version.updated_at,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError("document upload or version already exists") from exc

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_upload_session WHERE upload_id = %s",
                (upload_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise DocumentNotFoundError("upload was not found")
        return UploadSession.model_validate(_payload(row["payload"]))

    async def save_upload(self, session: UploadSession) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE document_upload_session SET state = %s, payload = %s::jsonb, "
                "updated_at = NOW() WHERE upload_id = %s RETURNING upload_id",
                (session.state.value, session.model_dump_json(), session.upload_id),
            )
            if await cursor.fetchone() is None:
                raise DocumentNotFoundError("upload was not found")

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_version WHERE document_id = %s AND version_id = %s",
                (document_id, version_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise DocumentNotFoundError("document version was not found")
        return DocumentVersion.model_validate(_payload(row["payload"]))

    async def save_version(self, version: DocumentVersion) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if version.active:
                await connection.execute(
                    "UPDATE document_version SET active = FALSE, "
                    "payload = jsonb_set(payload, '{active}', 'false'::jsonb), updated_at = NOW() "
                    "WHERE document_id = %s AND version_id <> %s AND active",
                    (version.document_id, version.version_id),
                )
            cursor = await connection.execute(
                "UPDATE document_version SET state = %s, active = %s, payload = %s::jsonb, "
                "updated_at = %s WHERE document_id = %s AND version_id = %s "
                "RETURNING version_id",
                (
                    version.state.value,
                    version.active,
                    version.model_dump_json(),
                    version.updated_at,
                    version.document_id,
                    version.version_id,
                ),
            )
            if await cursor.fetchone() is None:
                raise DocumentNotFoundError("document version was not found")

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_version WHERE document_id = %s "
                "ORDER BY created_at ASC, version_id ASC",
                (document_id,),
            )
            rows = await cursor.fetchall()
        if not rows:
            raise DocumentNotFoundError("document was not found")
        return tuple(DocumentVersion.model_validate(_payload(row["payload"])) for row in rows)

    async def list_uploads_by_state(self, state: str, *, limit: int) -> tuple[UploadSession, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("document upload state limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_upload_session WHERE state = %s "
                "ORDER BY created_at ASC, upload_id ASC LIMIT %s",
                (state, limit),
            )
            rows = await cursor.fetchall()
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
        _validate_worker_claim_input(owner=owner, lease_seconds=lease_seconds)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO document_worker_claim ("
                f"{_WORKER_CLAIM_COLUMNS}) VALUES ("
                "%s, %s, %s, %s, 1, 'active', clock_timestamp(), "
                "clock_timestamp() + (%s * INTERVAL '1 second'), NULL) "
                "ON CONFLICT (upload_id, stage) DO NOTHING "
                f"RETURNING {_WORKER_CLAIM_COLUMNS}",
                (upload_id, stage.value, owner, attempt_id, lease_seconds),
            )
            row = await cursor.fetchone()
            if row is not None:
                return _worker_claim(row)
            current_cursor = await connection.execute(
                f"SELECT {_WORKER_CLAIM_COLUMNS}, clock_timestamp() AS server_now "
                "FROM document_worker_claim WHERE upload_id = %s AND stage = %s FOR UPDATE",
                (upload_id, stage.value),
            )
            current_row = await current_cursor.fetchone()
            if current_row is None:
                raise RuntimeError("document worker claim disappeared during acquisition")
            current = _worker_claim(current_row)
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
            reclaimed_cursor = await connection.execute(
                "UPDATE document_worker_claim SET owner = %s, attempt_id = %s, "
                "revision = revision + 1, status = 'active', claimed_at = clock_timestamp(), "
                "lease_expires_at = clock_timestamp() + (%s * INTERVAL '1 second'), "
                "finished_at = NULL WHERE upload_id = %s AND stage = %s AND revision = %s "
                f"RETURNING {_WORKER_CLAIM_COLUMNS}",
                (
                    owner,
                    attempt_id,
                    lease_seconds,
                    upload_id,
                    stage.value,
                    current.revision,
                ),
            )
            reclaimed_row = await reclaimed_cursor.fetchone()
            if reclaimed_row is None:
                raise DocumentWorkerClaimConflictError("document worker claim conflict")
            return _worker_claim(reclaimed_row)

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
        _validate_worker_claim_input(owner=owner, lease_seconds=lease_seconds)
        return await self._update_worker_claim(
            upload_id,
            stage,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            assignment=(
                "revision = revision + 1, lease_expires_at = "
                "clock_timestamp() + (%s * INTERVAL '1 second')"
            ),
            assignment_params=(lease_seconds,),
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
        return await self._finish_worker_stage(
            upload_id,
            stage,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            status=DocumentWorkerClaimStatus.COMPLETED,
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
        return await self._finish_worker_stage(
            upload_id,
            stage,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            status=DocumentWorkerClaimStatus.RELEASED,
        )

    async def _finish_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        status: DocumentWorkerClaimStatus,
    ) -> DocumentWorkerClaim:
        try:
            return await self._update_worker_claim(
                upload_id,
                stage,
                owner=owner,
                attempt_id=attempt_id,
                expected_revision=expected_revision,
                assignment=(
                    "revision = revision + 1, status = %s, finished_at = clock_timestamp()"
                ),
                assignment_params=(status.value,),
            )
        except DocumentWorkerClaimConflictError:
            async with await self._connect() as connection:
                await self._timeout(connection)
                cursor = await connection.execute(
                    f"SELECT {_WORKER_CLAIM_COLUMNS} FROM document_worker_claim "
                    "WHERE upload_id = %s AND stage = %s",
                    (upload_id, stage.value),
                )
                row = await cursor.fetchone()
            if row is not None:
                current = _worker_claim(row)
                if (
                    current.status is status
                    and current.owner == owner
                    and current.attempt_id == attempt_id
                    and current.revision == expected_revision + 1
                ):
                    return current
            raise

    async def _update_worker_claim(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
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
            cursor = await connection.execute(
                f"UPDATE document_worker_claim SET {assignment} "
                "WHERE upload_id = %s AND stage = %s AND owner = %s AND attempt_id = %s "
                "AND revision = %s AND status = 'active' "
                "AND lease_expires_at > clock_timestamp() "
                f"RETURNING {_WORKER_CLAIM_COLUMNS}",
                (
                    *assignment_params,
                    upload_id,
                    stage.value,
                    owner,
                    attempt_id,
                    expected_revision,
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        return _worker_claim(row)

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


def _worker_claim(row: dict[str, Any]) -> DocumentWorkerClaim:
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


def _validate_worker_claim_input(*, owner: str, lease_seconds: int) -> None:
    if not owner or len(owner) > 256 or lease_seconds < 1 or lease_seconds > 3600:
        raise ValueError("document worker owner and lease MUST be valid")


__all__ = ["PostgresDocumentMetadataStore", "PostgresDocumentMetadataStoreConfig"]
