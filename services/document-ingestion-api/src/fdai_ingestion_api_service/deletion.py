"""API-owned governed deletion coordinator."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentAccessProvider,
    DocumentActivitySink,
    DocumentState,
    DocumentVersion,
    UploadSession,
)

from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
    PostgresDocumentMetadataStore,
)
from fdai_ingestion_api_service.adapters.storage import AzureDataLakeObjectStore
from fdai_ingestion_api_service.state_machine import transition


class ApiDocumentDeletionService:
    """Delete API-visible source, derived, and index records without worker imports."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: PostgresDocumentMetadataStore,
        objects: AzureDataLakeObjectStore,
        database: PostgresApiConfig,
        activity: DocumentActivitySink,
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._database = database
        self._activity = activity

    async def delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion:
        version = await self._metadata.get_version(document_id, version_id)
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if version.retention.legal_hold:
            raise ValueError("document version is subject to legal hold")
        session = await self._metadata.get_upload(version.upload_id)
        deleting = transition(version.state, DocumentState.DELETING)
        session = session.model_copy(update={"state": deleting})
        version = version.model_copy(
            update={
                "state": deleting,
                "available": False,
                "active": False,
                "updated_at": datetime.now(tz=UTC),
            }
        )
        await self._metadata.save_upload(session)
        await self._metadata.save_version(version)
        try:
            await self._delete_chunks(document_id, version_id)
            await self._objects.delete_artifact(document_id, version_id)
            await self._objects.delete(session.object_key)
        except Exception:
            await self._record(session, version, "document.deletion_pending", actor_id)
            raise
        deleted = transition(deleting, DocumentState.DELETED)
        session = session.model_copy(update={"state": deleted})
        version = version.model_copy(update={"state": deleted, "updated_at": datetime.now(tz=UTC)})
        await self._metadata.save_upload(session)
        await self._metadata.save_version(version)
        await self._record(session, version, "document.deleted", actor_id)
        return version

    async def _delete_chunks(self, document_id: UUID, version_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._database.dsn,
            connect_timeout=self._database.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "DELETE FROM knowledge_chunk WHERE metadata->>'document_id' = %s "
                "AND metadata->>'version_id' = %s",
                (str(document_id), str(version_id)),
            )

    async def _record(
        self,
        session: UploadSession,
        version: DocumentVersion,
        action: str,
        actor_id: str,
    ) -> None:
        record: dict[str, object] = {
            "action": action,
            "actor_id": actor_id,
            "collection_id": session.collection_id,
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "source_sha256": version.source_sha256,
            "state": version.state.value,
            "policy_version": version.retention.policy_version,
            "access_descriptor_ref": version.access.reference,
        }
        await self._activity.audit(record)
        await self._activity.publish(action, str(version.document_id), record)
