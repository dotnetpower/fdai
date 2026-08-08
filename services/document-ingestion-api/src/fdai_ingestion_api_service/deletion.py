"""API-owned governed deletion coordinator."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fdai_service_contracts import (
    DocumentAccessProvider,
    DocumentDeletionRequest,
    DocumentLifecycleEvent,
    DocumentState,
    DocumentUploadMetadataStore,
    DocumentVersion,
)

from fdai_ingestion_api_service.state_machine import transition


class ApiDocumentDeletionService:
    """Authorize deletion and enqueue worker-owned cleanup without direct writes."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentUploadMetadataStore,
    ) -> None:
        self._access = access
        self._metadata = metadata

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
        requested_at = datetime.now(tz=UTC)
        deleting_session = session.model_copy(
            update={"state": deleting, "revision": session.revision + 1}
        )
        deleting_version = version.model_copy(
            update={
                "state": deleting,
                "available": False,
                "active": False,
                "updated_at": requested_at,
                "revision": version.revision + 1,
            }
        )
        identity = f"document.delete:{version.version_id}:{deleting_version.revision}"
        request = DocumentDeletionRequest(
            request_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
            idempotency_key=identity,
            document_id=document_id,
            version_id=version_id,
            upload_id=version.upload_id,
            requested_by=actor_id,
            expected_upload_revision=deleting_session.revision,
            expected_version_revision=deleting_version.revision,
            requested_at=requested_at,
        )
        event = DocumentLifecycleEvent(
            event_id=request.request_id,
            idempotency_key=request.idempotency_key,
            topic="object.event",
            key=str(document_id),
            payload={
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "action": "document.deletion_requested",
                "event_type": "document.deletion_requested",
                "correlation_id": str(version.upload_id),
                "idempotency_key": identity,
                "resource_id": str(document_id),
                "resource_type": "document",
                "document_id": str(document_id),
                "deletion_request": request.model_dump(mode="json"),
            },
            created_at=requested_at,
        )
        await self._metadata.transition(
            deleting_session,
            deleting_version,
            expected_upload_state=session.state.value,
            expected_upload_revision=session.revision,
            expected_version_state=version.state.value,
            expected_version_revision=version.revision,
            event=event,
        )
        return deleting_version
