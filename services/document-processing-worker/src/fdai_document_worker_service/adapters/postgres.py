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

from fdai_document_worker_service.effects import (
    WorkerEffect,
    WorkerEffectKind,
    WorkerEffectStatus,
    worker_effect_id,
)

_CLAIM_COLUMNS = (
    "upload_id, stage, owner, attempt_id, revision, status, claimed_at, "
    "lease_expires_at, finished_at"
)
_EFFECT_COLUMNS = (
    "effect_id, upload_id, document_id, version_id, effect_kind, object_key, "
    "status, created_at, completed_at"
)
_READINESS_SQL: Final = """
SELECT
    has_table_privilege(current_user, 'document_upload_session', 'SELECT, UPDATE')
    AND has_table_privilege(current_user, 'document_version', 'SELECT, UPDATE')
    AND has_table_privilege(current_user, 'document_worker_claim', 'SELECT, INSERT, UPDATE')
    AND has_table_privilege(current_user, 'document_worker_outbox', 'SELECT, INSERT, UPDATE')
    AND has_table_privilege(current_user, 'document_worker_effect', 'SELECT, INSERT, UPDATE')
    AND has_table_privilege(current_user, 'knowledge_chunk', 'SELECT, INSERT, UPDATE, DELETE')
    AND has_table_privilege(current_user, 'state_kv', 'SELECT, INSERT, UPDATE, DELETE') AS ready
  FROM (VALUES (1)) AS probe(value)
  LEFT JOIN (
     SELECT upload_id, document_id, version_id, state, revision, payload,
            created_at, updated_at
       FROM document_upload_session
      LIMIT 0
  ) AS required_upload ON FALSE
  LEFT JOIN (
     SELECT document_id, version_id, upload_id, state, active, revision,
            payload, created_at, updated_at
       FROM document_version
      LIMIT 0
  ) AS required_version ON FALSE
  LEFT JOIN (
     SELECT upload_id, stage, owner, attempt_id, revision, status,
            claimed_at, lease_expires_at, finished_at
       FROM document_worker_claim
      LIMIT 0
  ) AS required_claim ON FALSE
  LEFT JOIN (
     SELECT event_id, idempotency_key, topic, partition_key, payload,
            created_at, published_at, next_attempt_at, attempt_count
       FROM document_worker_outbox
      LIMIT 0
  ) AS required_outbox ON FALSE
  LEFT JOIN (
     SELECT effect_id, upload_id, document_id, version_id, effect_kind,
            object_key, status, created_at, completed_at, attempt_count, next_attempt_at
       FROM document_worker_effect
      LIMIT 0
  ) AS required_effect ON FALSE
  LEFT JOIN (
     SELECT doc_id, chunk_id, text, source_ref, metadata, embedding
       FROM knowledge_chunk
      LIMIT 0
  ) AS required_chunks ON FALSE
  LEFT JOIN (
     SELECT key, value, updated_at
       FROM state_kv
      LIMIT 0
  ) AS required_state ON FALSE
"""


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
        """Verify required worker tables, columns, grants, and connectivity."""
        adapter = "postgres-document-metadata"
        try:
            async with asyncio.timeout(min(float(self._config.connect_timeout_s), 5.0)):
                async with await self._connect() as connection:
                    row = await (await connection.execute(_READINESS_SQL)).fetchone()
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        if row is None or row.get("ready") is not True:
            return live_unavailable_readiness(adapter, "required_schema_or_grants_missing")
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

    async def prepare_worker_effect(
        self,
        *,
        claim: DocumentWorkerClaim,
        kind: WorkerEffectKind,
        document_id: UUID,
        version_id: UUID,
        object_key: str,
    ) -> WorkerEffect:
        """Persist one immutable effect intent while the exact stage claim is active."""
        effect_id = worker_effect_id(kind, version_id)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._lock_active_claim(connection, claim)
            await connection.execute(
                "INSERT INTO document_worker_effect "
                "(effect_id, upload_id, document_id, version_id, effect_kind, object_key) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (effect_id) DO NOTHING",
                (
                    effect_id,
                    claim.upload_id,
                    document_id,
                    version_id,
                    kind.value,
                    object_key,
                ),
            )
            row = await (
                await connection.execute(
                    f"SELECT {_EFFECT_COLUMNS} FROM document_worker_effect "
                    "WHERE effect_id = %s FOR UPDATE",
                    (effect_id,),
                )
            ).fetchone()
        if row is None:
            raise RuntimeError("document worker effect disappeared during preparation")
        effect = _effect(row)
        if (
            effect.upload_id != claim.upload_id
            or effect.document_id != document_id
            or effect.version_id != version_id
            or effect.kind is not kind
            or effect.object_key != object_key
        ):
            raise DocumentLifecycleConflictError("document worker effect identity conflict")
        return effect

    async def get_worker_effect(
        self, upload_id: UUID, kind: WorkerEffectKind
    ) -> WorkerEffect | None:
        row = await self._one(
            f"SELECT {_EFFECT_COLUMNS} FROM document_worker_effect "
            "WHERE upload_id = %s AND effect_kind = %s",
            (upload_id, kind.value),
        )
        return None if row is None else _effect(row)

    async def claim_pending_worker_effects(self, *, limit: int) -> tuple[WorkerEffect, ...]:
        """Schedule one bounded pending-effect page for idempotent reconciliation."""
        if limit < 1 or limit > 1000:
            raise ValueError("document worker effect limit MUST be in [1, 1000]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            rows = await (
                await connection.execute(
                    f"SELECT {_EFFECT_COLUMNS} FROM document_worker_effect "
                    "WHERE status = 'pending' AND next_attempt_at <= clock_timestamp() "
                    "ORDER BY created_at, effect_id FOR UPDATE SKIP LOCKED LIMIT %s",
                    (limit,),
                )
            ).fetchall()
            if rows:
                await connection.execute(
                    "UPDATE document_worker_effect SET attempt_count = attempt_count + 1, "
                    "next_attempt_at = clock_timestamp() + INTERVAL '5 seconds' "
                    "WHERE effect_id = ANY(%s)",
                    ([row["effect_id"] for row in rows],),
                )
        return tuple(_effect(row) for row in rows)

    async def complete_worker_effect(self, effect_id: UUID) -> None:
        async with await self._connect() as connection:
            row = await (
                await connection.execute(
                    "UPDATE document_worker_effect SET status = 'completed', "
                    "completed_at = clock_timestamp() WHERE effect_id = %s "
                    f"AND status = 'pending' RETURNING {_EFFECT_COLUMNS}",
                    (effect_id,),
                )
            ).fetchone()
        if row is not None:
            return
        current = await self._one(
            f"SELECT {_EFFECT_COLUMNS} FROM document_worker_effect WHERE effect_id = %s",
            (effect_id,),
        )
        if current is None or _effect(current).status is not WorkerEffectStatus.COMPLETED:
            raise DocumentLifecycleConflictError("document worker effect completion conflict")

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
        return await self.list_uploads_by_state_after(state, after_upload_id=None, limit=limit)

    async def list_uploads_by_state_after(
        self,
        state: str,
        *,
        after_upload_id: UUID | None,
        limit: int,
    ) -> tuple[UploadSession, ...]:
        """List one stable UUID-ordered page after the supplied reconciliation cursor."""
        if limit < 1 or limit > 1000:
            raise ValueError("document upload state limit MUST be in [1, 1000]")
        if after_upload_id is None:
            rows = await self._many(
                "SELECT payload FROM document_upload_session WHERE state = %s "
                "ORDER BY upload_id ASC LIMIT %s",
                (state, limit),
            )
        else:
            rows = await self._many(
                "SELECT payload FROM document_upload_session WHERE state = %s "
                "AND upload_id > %s ORDER BY upload_id ASC LIMIT %s",
                (state, after_upload_id, limit),
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


def _effect(row: dict[str, Any]) -> WorkerEffect:
    return WorkerEffect(
        effect_id=row["effect_id"],
        upload_id=row["upload_id"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        kind=WorkerEffectKind(row["effect_kind"]),
        object_key=str(row["object_key"]),
        status=WorkerEffectStatus(row["status"]),
        created_at=row["created_at"],
        completed_at=row["completed_at"],
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
