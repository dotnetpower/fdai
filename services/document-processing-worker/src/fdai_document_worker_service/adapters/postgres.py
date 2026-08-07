"""PostgreSQL document metadata and durable worker-claim adapter."""

# ruff: noqa: S608 - SQL fragments are private fixed literals.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentNotFoundError,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    UploadSession,
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

    async def create(self, session: UploadSession, version: DocumentVersion) -> None:
        raise PermissionError("the worker database role cannot create uploads")

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        row = await self._one(
            "SELECT payload FROM document_upload_session WHERE upload_id = %s",
            (upload_id,),
        )
        if row is None:
            raise DocumentNotFoundError("upload was not found")
        return UploadSession.model_validate(_payload(row["payload"]))

    async def save_upload(self, session: UploadSession) -> None:
        await self._update_record(
            "UPDATE document_upload_session SET state = %s, payload = %s::jsonb, "
            "updated_at = NOW() WHERE upload_id = %s RETURNING upload_id",
            (session.state.value, session.model_dump_json(), session.upload_id),
            "upload was not found",
        )

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        row = await self._one(
            "SELECT payload FROM document_version WHERE document_id = %s AND version_id = %s",
            (document_id, version_id),
        )
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
                "updated_at = %s WHERE document_id = %s AND version_id = %s RETURNING version_id",
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

    async def _one(self, query: str, params: tuple[object, ...]) -> dict[str, Any] | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await (await connection.execute(query, params)).fetchone()

    async def _many(self, query: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await (await connection.execute(query, params)).fetchall()

    async def _update_record(self, query: str, params: tuple[object, ...], not_found: str) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if await (await connection.execute(query, params)).fetchone() is None:
                raise DocumentNotFoundError(not_found)

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
