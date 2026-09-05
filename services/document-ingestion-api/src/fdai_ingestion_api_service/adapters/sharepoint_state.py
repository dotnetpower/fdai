"""PostgreSQL cursor and item projection for SharePoint delta synchronization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentDeletionRequest,
    DocumentLifecycleEvent,
    DocumentState,
    DocumentVersion,
    UploadSession,
)
from psycopg.rows import dict_row

from fdai_ingestion_api_service.adapters.sharepoint import (
    SharePointDeltaCursor,
    SharePointDeltaItem,
    SharePointPendingPage,
)


@dataclass(frozen=True, slots=True)
class ConnectorDocumentBinding:
    document_id: UUID
    version_id: UUID
    source_revision: str


class ConnectorBindingConflictError(RuntimeError):
    """A newer source event won before its document binding committed."""


class PostgresSharePointDeltaStore:
    """Persist one fenced cursor and idempotent access-bound item projection."""

    def __init__(self, *, dsn: str, statement_timeout_ms: int = 15_000) -> None:
        if not dsn:
            raise ValueError("SharePoint delta DSN MUST NOT be empty")
        if statement_timeout_ms < 1:
            raise ValueError("SharePoint delta timeout MUST be positive")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms

    async def load(self, connector_id: str) -> SharePointDeltaCursor | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            row = await (
                await connection.execute(
                    "SELECT payload FROM document_connector_cursor WHERE connector_id = %s",
                    (connector_id,),
                )
            ).fetchone()
        if row is None:
            return None
        return _cursor(row["payload"])

    async def compare_and_swap(
        self, *, expected_revision: int, cursor: SharePointDeltaCursor
    ) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if expected_revision == 0:
                result = await connection.execute(
                    "INSERT INTO document_connector_cursor "
                    "(connector_id, revision, payload, updated_at) "
                    "VALUES (%s, %s, %s::jsonb, NOW()) "
                    "ON CONFLICT (connector_id) DO NOTHING RETURNING connector_id",
                    (cursor.connector_id, cursor.revision, _cursor_json(cursor)),
                )
            else:
                result = await connection.execute(
                    "UPDATE document_connector_cursor "
                    "SET revision = %s, payload = %s::jsonb, updated_at = NOW() "
                    "WHERE connector_id = %s AND revision = %s RETURNING connector_id",
                    (
                        cursor.revision,
                        _cursor_json(cursor),
                        cursor.connector_id,
                        expected_revision,
                    ),
                )
            return await result.fetchone() is not None

    async def apply_batch(
        self,
        *,
        connector_id: str,
        collection_id: str,
        access_descriptor_ref: str,
        idempotency_key: str,
        items: Sequence[SharePointDeltaItem],
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            inserted = await connection.execute(
                "INSERT INTO document_connector_batch "
                "(idempotency_key, connector_id, collection_id, access_descriptor_ref) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING idempotency_key",
                (
                    idempotency_key,
                    connector_id,
                    collection_id,
                    access_descriptor_ref,
                ),
            )
            if await inserted.fetchone() is None:
                existing = await (
                    await connection.execute(
                        "SELECT connector_id, collection_id, access_descriptor_ref "
                        "FROM document_connector_batch WHERE idempotency_key = %s",
                        (idempotency_key,),
                    )
                ).fetchone()
                if existing != {
                    "connector_id": connector_id,
                    "collection_id": collection_id,
                    "access_descriptor_ref": access_descriptor_ref,
                }:
                    raise RuntimeError("SharePoint delta batch binding changed")
                return
            for item in items:
                changed = await connection.execute(
                    "INSERT INTO document_connector_item "
                    "(connector_id, source_item_id, source_revision, source_sequence, "
                    "source_name, size_bytes, content_sha256, deleted, collection_id, "
                    "access_descriptor_ref, sync_epoch, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) "
                    "ON CONFLICT (connector_id, source_item_id) DO UPDATE SET "
                    "source_revision = EXCLUDED.source_revision, "
                    "source_sequence = EXCLUDED.source_sequence, "
                    "source_name = EXCLUDED.source_name, size_bytes = EXCLUDED.size_bytes, "
                    "content_sha256 = EXCLUDED.content_sha256, "
                    "deleted = EXCLUDED.deleted, collection_id = EXCLUDED.collection_id, "
                    "access_descriptor_ref = EXCLUDED.access_descriptor_ref, "
                    "sync_epoch = EXCLUDED.sync_epoch, "
                    "ingestion_outcome = 'pending', failure_code = NULL, updated_at = NOW() "
                    "WHERE EXCLUDED.source_sequence IS NULL "
                    "OR document_connector_item.source_sequence IS NULL "
                    "OR EXCLUDED.source_sequence > document_connector_item.source_sequence "
                    "OR (EXCLUDED.source_sequence = document_connector_item.source_sequence "
                    "AND EXCLUDED.source_revision = document_connector_item.source_revision "
                    "AND EXCLUDED.deleted = document_connector_item.deleted "
                    "AND EXCLUDED.source_name IS NOT DISTINCT FROM "
                    "document_connector_item.source_name "
                    "AND EXCLUDED.size_bytes = document_connector_item.size_bytes "
                    "AND EXCLUDED.content_sha256 IS NOT DISTINCT FROM "
                    "document_connector_item.content_sha256) "
                    "RETURNING deleted",
                    (
                        connector_id,
                        item.source_item_id,
                        item.source_revision,
                        item.source_sequence,
                        item.source_name,
                        item.size_bytes,
                        item.content_sha256,
                        item.deleted,
                        collection_id,
                        access_descriptor_ref,
                        item.sync_epoch,
                    ),
                )
                if await changed.fetchone() is not None and item.deleted:
                    await self._propagate_deletion(
                        connection,
                        connector_id=connector_id,
                        source_item_id=item.source_item_id,
                    )

    async def bind_document(
        self,
        *,
        connector_id: str,
        source_item_id: str,
        document_id: UUID,
        version_id: UUID,
        source_revision: str,
        source_sequence: int,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            prior = await (
                await connection.execute(
                    "SELECT document_id, version_id, bound_source_revision "
                    "FROM document_connector_item "
                    "WHERE connector_id = %s AND source_item_id = %s FOR UPDATE",
                    (connector_id, source_item_id),
                )
            ).fetchone()
            if prior is None:
                raise ConnectorBindingConflictError(
                    "SharePoint connector item disappeared before document binding"
                )
            displaced_revision = (
                str(prior["bound_source_revision"])
                if prior["version_id"] is not None and UUID(str(prior["version_id"])) != version_id
                else None
            )
            updated = await connection.execute(
                "UPDATE document_connector_item SET document_id = %s, version_id = %s, "
                "bound_source_revision = %s, ingestion_outcome = 'accepted', "
                "failure_code = NULL, updated_at = NOW() "
                "WHERE connector_id = %s AND source_item_id = %s AND NOT deleted "
                "AND (document_id IS NULL OR document_id = %s) "
                "AND source_revision = %s AND source_sequence = %s "
                "RETURNING source_item_id",
                (
                    document_id,
                    version_id,
                    source_revision,
                    connector_id,
                    source_item_id,
                    document_id,
                    source_revision,
                    source_sequence,
                ),
            )
            if await updated.fetchone() is None:
                raise ConnectorBindingConflictError(
                    "SharePoint connector item cannot accept stale document binding"
                )
            if displaced_revision is not None:
                await self._queue_cancellation(
                    connection,
                    connector_id=connector_id,
                    source_item_id=source_item_id,
                    source_revision=displaced_revision,
                )

    async def record_rejection(
        self,
        *,
        connector_id: str,
        source_item_id: str,
        source_revision: str,
        source_sequence: int,
        failure_code: str,
    ) -> None:
        if not failure_code or len(failure_code) > 128:
            raise ValueError("connector rejection code MUST be non-empty and bounded")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            updated = await connection.execute(
                "UPDATE document_connector_item "
                "SET ingestion_outcome = 'rejected', failure_code = %s, updated_at = NOW() "
                "WHERE connector_id = %s AND source_item_id = %s "
                "AND source_revision = %s AND source_sequence = %s AND NOT deleted "
                "RETURNING source_item_id",
                (
                    failure_code,
                    connector_id,
                    source_item_id,
                    source_revision,
                    source_sequence,
                ),
            )
            if await updated.fetchone() is None:
                raise ConnectorBindingConflictError(
                    "SharePoint rejection no longer matches the source event"
                )

    async def pending_cancellations(
        self, *, connector_id: str, source_item_id: str
    ) -> tuple[str, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT source_revision FROM document_connector_cancellation "
                    "WHERE connector_id = %s AND source_item_id = %s AND status = 'pending' "
                    "ORDER BY created_at, source_revision LIMIT 64",
                    (connector_id, source_item_id),
                )
            ).fetchall()
        return tuple(str(row["source_revision"]) for row in rows)

    async def pending_cancellation_items(self, *, connector_id: str, limit: int) -> tuple[str, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("connector cancellation item limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT source_item_id, min(created_at) AS oldest "
                    "FROM document_connector_cancellation "
                    "WHERE connector_id = %s AND status = 'pending' "
                    "GROUP BY source_item_id ORDER BY oldest, source_item_id LIMIT %s",
                    (connector_id, limit),
                )
            ).fetchall()
        return tuple(str(row["source_item_id"]) for row in rows)

    async def complete_cancellation(
        self, *, connector_id: str, source_item_id: str, source_revision: str
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            updated = await connection.execute(
                "UPDATE document_connector_cancellation "
                "SET status = 'completed', completed_at = NOW() "
                "WHERE connector_id = %s AND source_item_id = %s "
                "AND source_revision = %s AND status = 'pending' "
                "RETURNING source_revision",
                (connector_id, source_item_id, source_revision),
            )
            if await updated.fetchone() is None:
                raise ConnectorBindingConflictError(
                    "connector cancellation no longer matches pending state"
                )

    async def queue_cancellation(
        self, *, connector_id: str, source_item_id: str, source_revision: str
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._queue_cancellation(
                connection,
                connector_id=connector_id,
                source_item_id=source_item_id,
                source_revision=source_revision,
            )

    @staticmethod
    async def _queue_cancellation(
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        connector_id: str,
        source_item_id: str,
        source_revision: str,
    ) -> None:
        _validate_cancellation_revision(source_revision)
        await connection.execute(
            "INSERT INTO document_connector_cancellation "
            "(connector_id, source_item_id, source_revision) VALUES (%s, %s, %s) "
            "ON CONFLICT (connector_id, source_item_id, source_revision) DO NOTHING",
            (connector_id, source_item_id, source_revision),
        )

    async def get_binding(
        self, *, connector_id: str, source_item_id: str
    ) -> ConnectorDocumentBinding | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            row = await (
                await connection.execute(
                    "SELECT document_id, version_id, bound_source_revision "
                    "FROM document_connector_item "
                    "WHERE connector_id = %s AND source_item_id = %s AND NOT deleted",
                    (connector_id, source_item_id),
                )
            ).fetchone()
        if row is None or row["document_id"] is None:
            return None
        return ConnectorDocumentBinding(
            document_id=UUID(str(row["document_id"])),
            version_id=UUID(str(row["version_id"])),
            source_revision=str(row["bound_source_revision"]),
        )

    async def event_matches(
        self,
        *,
        connector_id: str,
        source_item_id: str,
        source_revision: str,
        source_sequence: int,
        source_name: str | None,
        size_bytes: int,
        content_sha256: str | None,
        deleted: bool,
    ) -> bool:
        async with await self._connect() as connection:
            await self._timeout(connection)
            row = await (
                await connection.execute(
                    "SELECT 1 AS matched FROM document_connector_item "
                    "WHERE connector_id = %s AND source_item_id = %s "
                    "AND source_revision = %s AND source_sequence = %s "
                    "AND source_name IS NOT DISTINCT FROM %s AND size_bytes = %s "
                    "AND content_sha256 IS NOT DISTINCT FROM %s AND deleted = %s",
                    (
                        connector_id,
                        source_item_id,
                        source_revision,
                        source_sequence,
                        source_name,
                        size_bytes,
                        content_sha256,
                        deleted,
                    ),
                )
            ).fetchone()
        return row is not None

    async def reconcile_deletions(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("SharePoint deletion reconciliation limit MUST be in [1, 1000]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT connector_id, source_item_id FROM document_connector_item "
                    "WHERE deleted AND deletion_pending AND document_id IS NOT NULL "
                    "ORDER BY updated_at, connector_id, source_item_id "
                    "FOR UPDATE SKIP LOCKED LIMIT %s",
                    (limit,),
                )
            ).fetchall()
            for row in rows:
                await self._propagate_deletion(
                    connection,
                    connector_id=str(row["connector_id"]),
                    source_item_id=str(row["source_item_id"]),
                )
        return len(rows)

    async def finalize_resync(self, *, connector_id: str, sync_epoch: int, limit: int) -> bool:
        if sync_epoch < 1 or not 1 <= limit <= 1000:
            raise ValueError("SharePoint resync epoch and limit are invalid")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT source_item_id FROM document_connector_item "
                    "WHERE connector_id = %s AND NOT deleted AND sync_epoch < %s "
                    "ORDER BY source_item_id FOR UPDATE SKIP LOCKED LIMIT %s",
                    (connector_id, sync_epoch, limit),
                )
            ).fetchall()
            for row in rows:
                source_item_id = str(row["source_item_id"])
                await connection.execute(
                    "UPDATE document_connector_item SET deleted = TRUE, "
                    "source_revision = %s, source_sequence = COALESCE(source_sequence, 0) + 1, "
                    "content_sha256 = NULL, sync_epoch = %s, "
                    "ingestion_outcome = 'pending', failure_code = NULL, updated_at = NOW() "
                    "WHERE connector_id = %s AND source_item_id = %s",
                    (
                        f"resync-missing:{sync_epoch}",
                        sync_epoch,
                        connector_id,
                        source_item_id,
                    ),
                )
                await self._propagate_deletion(
                    connection,
                    connector_id=connector_id,
                    source_item_id=source_item_id,
                )
            remaining = await (
                await connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM document_connector_item "
                    "WHERE connector_id = %s AND NOT deleted AND sync_epoch < %s) "
                    "AS remaining",
                    (connector_id, sync_epoch),
                )
            ).fetchone()
        return remaining is not None and remaining["remaining"] is False

    async def _propagate_deletion(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        connector_id: str,
        source_item_id: str,
    ) -> None:
        binding = await (
            await connection.execute(
                "SELECT document_id, version_id FROM document_connector_item "
                "WHERE connector_id = %s AND source_item_id = %s FOR UPDATE",
                (connector_id, source_item_id),
            )
        ).fetchone()
        if binding is None or binding["document_id"] is None:
            await self._set_item_outcome(
                connection,
                connector_id,
                source_item_id,
                outcome="accepted",
            )
            return
        document_id = UUID(str(binding["document_id"]))
        version_id = UUID(str(binding["version_id"]))
        version_row = await (
            await connection.execute(
                "SELECT payload FROM document_version "
                "WHERE document_id = %s AND version_id = %s FOR UPDATE",
                (document_id, version_id),
            )
        ).fetchone()
        if version_row is None:
            raise RuntimeError("SharePoint linked document version disappeared")
        version = DocumentVersion.model_validate(version_row["payload"])
        if version.state in {DocumentState.DELETING, DocumentState.DELETED}:
            await self._set_deletion_pending(
                connection, connector_id, source_item_id, pending=False
            )
            return
        if version.retention.legal_hold:
            await self._set_deletion_pending(connection, connector_id, source_item_id, pending=True)
            return
        upload_row = await (
            await connection.execute(
                "SELECT payload FROM document_upload_session WHERE upload_id = %s FOR UPDATE",
                (version.upload_id,),
            )
        ).fetchone()
        if upload_row is None:
            raise RuntimeError("SharePoint linked upload disappeared")
        session = UploadSession.model_validate(upload_row["payload"])
        now = datetime.now(tz=UTC)
        deleting_session = session.model_copy(
            update={
                "state": DocumentState.DELETING,
                "failure_code": "linked_source_deleted",
                "revision": session.revision + 1,
            }
        )
        deleting_version = version.model_copy(
            update={
                "state": DocumentState.DELETING,
                "active": False,
                "available": False,
                "failure_code": "linked_source_deleted",
                "updated_at": now,
                "revision": version.revision + 1,
            }
        )
        upload_updated = await connection.execute(
            "UPDATE document_upload_session SET state = %s, revision = %s, "
            "payload = %s::jsonb, updated_at = NOW() "
            "WHERE upload_id = %s AND state = %s AND revision = %s RETURNING upload_id",
            (
                DocumentState.DELETING.value,
                deleting_session.revision,
                deleting_session.model_dump_json(),
                session.upload_id,
                session.state.value,
                session.revision,
            ),
        )
        version_updated = await connection.execute(
            "UPDATE document_version SET state = %s, active = FALSE, revision = %s, "
            "payload = %s::jsonb, updated_at = %s "
            "WHERE document_id = %s AND version_id = %s AND state = %s "
            "AND revision = %s RETURNING version_id",
            (
                DocumentState.DELETING.value,
                deleting_version.revision,
                deleting_version.model_dump_json(),
                now,
                document_id,
                version_id,
                version.state.value,
                version.revision,
            ),
        )
        if await upload_updated.fetchone() is None or await version_updated.fetchone() is None:
            raise RuntimeError("SharePoint linked deletion lifecycle CAS conflict")
        event = _deletion_event(deleting_session, deleting_version, now=now)
        await connection.execute(
            "INSERT INTO document_api_outbox "
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
        await self._set_deletion_pending(connection, connector_id, source_item_id, pending=False)
        await self._set_item_outcome(
            connection,
            connector_id,
            source_item_id,
            outcome="accepted",
        )

    @staticmethod
    async def _set_deletion_pending(
        connection: psycopg.AsyncConnection[dict[str, Any]],
        connector_id: str,
        source_item_id: str,
        *,
        pending: bool,
    ) -> None:
        await connection.execute(
            "UPDATE document_connector_item SET deletion_pending = %s, updated_at = NOW() "
            "WHERE connector_id = %s AND source_item_id = %s",
            (pending, connector_id, source_item_id),
        )

    @staticmethod
    async def _set_item_outcome(
        connection: psycopg.AsyncConnection[dict[str, Any]],
        connector_id: str,
        source_item_id: str,
        *,
        outcome: str,
    ) -> None:
        await connection.execute(
            "UPDATE document_connector_item "
            "SET ingestion_outcome = %s, failure_code = NULL, updated_at = NOW() "
            "WHERE connector_id = %s AND source_item_id = %s",
            (outcome, connector_id, source_item_id),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)

    async def _timeout(self, connection: psycopg.AsyncConnection[dict[str, Any]]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._statement_timeout_ms),),
        )


def _cursor_json(cursor: SharePointDeltaCursor) -> str:
    pending = cursor.pending
    return json.dumps(
        {
            "connector_id": cursor.connector_id,
            "revision": cursor.revision,
            "delta_url": cursor.delta_url,
            "binding_digest": cursor.binding_digest,
            "resync_epoch": cursor.resync_epoch,
            "resync_active": cursor.resync_active,
            "pending": (
                None
                if pending is None
                else {
                    "binding_digest": pending.binding_digest,
                    "idempotency_key": pending.idempotency_key,
                    "items": [
                        {
                            "source_item_id": item.source_item_id,
                            "source_revision": item.source_revision,
                            "source_sequence": item.source_sequence,
                            "source_name": item.source_name,
                            "size_bytes": item.size_bytes,
                            "content_sha256": item.content_sha256,
                            "media_type": item.media_type,
                            "sync_epoch": item.sync_epoch,
                            "deleted": item.deleted,
                        }
                        for item in pending.items
                    ],
                    "continuation_url": pending.continuation_url,
                    "has_more": pending.has_more,
                }
            ),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _cursor(value: object) -> SharePointDeltaCursor:
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise RuntimeError("SharePoint cursor payload is invalid")
    pending_payload = payload.get("pending")
    pending = None
    if pending_payload is not None:
        if not isinstance(pending_payload, dict):
            raise RuntimeError("SharePoint pending cursor payload is invalid")
        raw_items = pending_payload.get("items")
        if not isinstance(raw_items, list):
            raise RuntimeError("SharePoint pending cursor items are invalid")
        pending = SharePointPendingPage(
            binding_digest=_string(pending_payload, "binding_digest"),
            idempotency_key=_string(pending_payload, "idempotency_key"),
            items=tuple(
                SharePointDeltaItem(
                    source_item_id=_string(item, "source_item_id"),
                    source_revision=_string(item, "source_revision"),
                    source_sequence=_optional_integer(item, "source_sequence"),
                    source_name=_optional_string(item, "source_name"),
                    size_bytes=_integer(item, "size_bytes"),
                    content_sha256=_optional_string(item, "content_sha256"),
                    media_type=_optional_string(item, "media_type") or "application/octet-stream",
                    sync_epoch=_optional_integer(item, "sync_epoch") or 0,
                    deleted=_boolean(item, "deleted"),
                )
                for item in raw_items
                if isinstance(item, dict)
            ),
            continuation_url=_string(pending_payload, "continuation_url"),
            has_more=_boolean(pending_payload, "has_more"),
        )
        if len(pending.items) != len(raw_items):
            raise RuntimeError("SharePoint pending cursor contains invalid items")
    return SharePointDeltaCursor(
        connector_id=_string(payload, "connector_id"),
        revision=_integer(payload, "revision"),
        delta_url=_optional_string(payload, "delta_url"),
        binding_digest=_optional_string(payload, "binding_digest"),
        pending=pending,
        resync_epoch=_optional_integer(payload, "resync_epoch") or 0,
        resync_active=_optional_boolean(payload, "resync_active") or False,
    )


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"SharePoint cursor {key} is invalid")
    return value


def _optional_boolean(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RuntimeError(f"SharePoint cursor {key} is invalid")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"SharePoint cursor {key} is invalid")
    return value


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"SharePoint cursor {key} is invalid")
    return value


def _optional_integer(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"SharePoint cursor {key} is invalid")
    return value


def _boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"SharePoint cursor {key} is invalid")
    return value


def _validate_cancellation_revision(source_revision: str) -> None:
    if not 0 < len(source_revision) <= 512:
        raise ValueError("connector cancellation revision MUST be in [1, 512] characters")


def _deletion_event(
    session: UploadSession, version: DocumentVersion, *, now: datetime
) -> DocumentLifecycleEvent:
    identity = f"document.connector_deleted:{version.version_id}:{version.revision}"
    request = DocumentDeletionRequest(
        request_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
        idempotency_key=identity,
        document_id=version.document_id,
        version_id=version.version_id,
        upload_id=version.upload_id,
        requested_by="sharepoint-connector",
        expected_upload_revision=session.revision,
        expected_version_revision=version.revision,
        requested_at=now,
    )
    return DocumentLifecycleEvent(
        event_id=request.request_id,
        idempotency_key=identity,
        topic="object.event",
        key=str(version.document_id),
        payload={
            "producer_principal": "Huginn",
            "kind": "document_ingestion",
            "action": "document.deletion_requested",
            "event_type": "document.deletion_requested",
            "correlation_id": str(version.upload_id),
            "idempotency_key": identity,
            "resource_id": str(version.document_id),
            "resource_type": "document",
            "document_id": str(version.document_id),
            "deletion_request": request.model_dump(mode="json"),
        },
        created_at=now,
    )
