"""Governed immutable-source download with authorization and audit admission."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentLifecycleEvent,
    DocumentObjectStore,
    DocumentState,
    DocumentUploadMetadataStore,
    ProtectionState,
)

from fdai_ingestion_api_service.providers import DocumentDownload


class GovernedDocumentDownload:
    """Admit an unprotected source download only after durable audit enqueue."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentUploadMetadataStore,
        objects: DocumentObjectStore,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or uuid4

    async def download(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentDownload:
        """Return a source stream only for a current indexed and unprotected version."""
        version = await self._metadata.get_version(document_id, version_id)
        await self._access.authorize_read(
            actor_id=actor_id,
            actor_groups=actor_groups,
            version=version,
        )
        if (
            not version.active
            or not version.available
            or version.state not in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
        ):
            raise DocumentAccessDeniedError("document version is not available for download")
        if version.protection_state not in {
            ProtectionState.NONE,
            ProtectionState.LABELED_UNENCRYPTED,
        }:
            raise DocumentAccessDeniedError(
                "protected source download requires purpose-specific authorization"
            )
        session = await self._metadata.get_upload(version.upload_id)
        if session.document_id != document_id or session.version_id != version_id:
            raise DocumentAccessDeniedError("document download binding changed")

        event_id = self._id_factory()
        requested_at = self._clock()
        await self._metadata.enqueue_event(
            DocumentLifecycleEvent(
                event_id=event_id,
                idempotency_key=f"document.source_download_requested:{event_id}",
                topic="object.event",
                key=str(document_id),
                payload={
                    "producer_principal": "Huginn",
                    "kind": "document_ingestion",
                    "action": "document.source_download_requested",
                    "event_type": "document.source_download_requested",
                    "correlation_id": str(version.upload_id),
                    "idempotency_key": f"document.source_download_requested:{event_id}",
                    "resource_id": str(document_id),
                    "resource_type": "document",
                    "document_id": str(document_id),
                    "version_id": str(version_id),
                    "actor_id": actor_id,
                },
                created_at=requested_at,
            )
        )
        return DocumentDownload(
            version=version,
            content=self._objects.read(session.object_key),
        )
