"""API-owned governed deletion coordinator."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fdai_service_contracts import (
    DocumentAccessProvider,
    DocumentDeletionRequest,
    DocumentDisposition,
    DocumentIndexState,
    DocumentLifecycleEvent,
    DocumentRetentionState,
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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._clock = clock or (lambda: datetime.now(tz=UTC))

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
        return await self._request_deletion(
            version=version,
            requested_by=actor_id,
            identity_prefix="document.delete",
            reason="operator_request",
        )

    async def expire(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion:
        """Submit deterministic policy expiry without assuming the uploader's identity."""
        version = await self._metadata.get_version(document_id, version_id)
        if version.disposition not in {
            DocumentDisposition.SESSION_EPHEMERAL,
            DocumentDisposition.WORKSPACE_DRAFT,
        }:
            raise ValueError("only temporary or draft documents can expire automatically")
        deadline = _expiry_deadline(version)
        if deadline is None or deadline > self._clock():
            raise ValueError("document version is not due for retention expiry")
        return await self._request_deletion(
            version=version,
            requested_by="retention-reconciler",
            identity_prefix=f"document.expire:{deadline.isoformat()}",
            reason="retention_expiry",
        )

    async def _request_deletion(
        self,
        *,
        version: DocumentVersion,
        requested_by: str,
        identity_prefix: str,
        reason: str,
    ) -> DocumentVersion:
        if version.retention.legal_hold:
            raise ValueError("document version is subject to legal hold")
        if version.state in {DocumentState.DELETING, DocumentState.DELETED}:
            return version
        session = await self._metadata.get_upload(version.upload_id)
        deleting = transition(version.state, DocumentState.DELETING)
        requested_at = self._clock()
        deleting_session = session.model_copy(
            update={
                "state": deleting,
                "index_state": DocumentIndexState.TOMBSTONED,
                "retention_state": DocumentRetentionState.TOMBSTONED,
                "revision": session.revision + 1,
            }
        )
        deleting_version = version.model_copy(
            update={
                "state": deleting,
                "available": False,
                "active": False,
                "index_state": DocumentIndexState.TOMBSTONED,
                "retention_state": DocumentRetentionState.TOMBSTONED,
                "updated_at": requested_at,
                "revision": version.revision + 1,
            }
        )
        identity = f"{identity_prefix}:{version.version_id}"
        request = DocumentDeletionRequest(
            request_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
            idempotency_key=identity,
            document_id=version.document_id,
            version_id=version.version_id,
            upload_id=version.upload_id,
            requested_by=requested_by,
            expected_upload_revision=deleting_session.revision,
            expected_version_revision=deleting_version.revision,
            requested_at=requested_at,
        )
        event = DocumentLifecycleEvent(
            event_id=request.request_id,
            idempotency_key=request.idempotency_key,
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
                "deletion_reason": reason,
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


def _expiry_deadline(version: DocumentVersion) -> datetime | None:
    deadlines = tuple(
        deadline
        for deadline in (
            version.retention.source_expires_at,
            version.retention.derived_expires_at,
        )
        if deadline is not None
    )
    return min(deadlines) if deadlines else None
