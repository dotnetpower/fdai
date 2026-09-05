"""Worker-owned tombstone, cleanup, and purge-verification lifecycle."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai_service_contracts import (
    DocumentArtifactStore,
    DocumentIndex,
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentPurgeVerificationReceipt,
    DocumentRetentionState,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    PromotableDocumentObjectStore,
    SourceStorageMode,
    UploadSession,
    WorkerDocumentObjectStore,
)

from fdai_document_worker_service.effects import WorkerEffect, WorkerMetadataStore
from fdai_document_worker_service.purge import DocumentPurgeVerifier, PurgeVerificationError
from fdai_document_worker_service.state_machine import transition

_ClaimReader = Callable[[], DocumentWorkerClaim]


@runtime_checkable
class TombstonableDocumentIndex(Protocol):
    async def tombstone(self, document_id: UUID, version_id: UUID) -> None: ...


class DocumentDeletionLifecycle:
    """Converge deletion in index, artifact, source, then verification order."""

    def __init__(
        self,
        *,
        metadata: WorkerMetadataStore,
        objects: WorkerDocumentObjectStore,
        artifacts: DocumentArtifactStore,
        index: DocumentIndex,
        purge_verifier: DocumentPurgeVerifier | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._metadata = metadata
        self._objects = objects
        self._artifacts = artifacts
        self._index = index
        self._purge_verifier = purge_verifier
        self._clock = clock

    async def complete_cleanup(
        self,
        effect: WorkerEffect,
        session: UploadSession,
        version: DocumentVersion,
        claim: _ClaimReader,
        *,
        actor_id: str,
    ) -> DocumentVersion:
        """Run idempotent cleanup and close only after a verified receipt."""
        if effect.object_key != session.object_key:
            raise DocumentLifecycleConflictError("deletion cleanup source target changed")
        if (
            version.state is DocumentState.DELETED
            and version.index_state is DocumentIndexState.PURGED
            and version.retention_state is DocumentRetentionState.PURGED
        ):
            await self._metadata.complete_worker_effect(effect.effect_id)
            return version
        session, version = await self._tombstone(session, version, claim)
        await self._assert_active_claim(session.upload_id, claim)
        if isinstance(self._index, TombstonableDocumentIndex):
            await self._index.tombstone(version.document_id, version.version_id)
        if version.retention.legal_hold:
            raise PurgeVerificationError("legal hold blocks physical document cleanup")
        await self._assert_active_claim(session.upload_id, claim)
        await self._index.delete(version.document_id, version.version_id)
        await self._assert_active_claim(session.upload_id, claim)
        await self._artifacts.delete(version.document_id, version.version_id)
        object_keys = {session.object_key}
        if session.storage_mode is SourceStorageMode.MANAGED_COPY and isinstance(
            self._objects, PromotableDocumentObjectStore
        ):
            object_keys.add(self._objects.governed_key(session))
        for object_key in sorted(object_keys):
            await self._assert_active_claim(session.upload_id, claim)
            await self._objects.delete(object_key)
        session, version = await self._set_purge_pending(session, version, claim)
        if self._purge_verifier is None:
            raise PurgeVerificationError("document purge verifier is not configured")
        await self._assert_active_claim(session.upload_id, claim)
        receipt = await self._purge_verifier.verify(
            document_id=version.document_id,
            version_id=version.version_id,
            source_object_keys=tuple(sorted(object_keys)),
        )
        if not receipt.verified:
            raise PurgeVerificationError("document purge left residue or a deletion blocker")
        if version.state in {DocumentState.DELETING, DocumentState.DELETED}:
            session, version = await self._advance_deleted(
                session,
                version,
                claim,
                actor_id=actor_id,
                receipt=receipt,
            )
        await self._metadata.complete_worker_effect(effect.effect_id)
        return version

    async def mark_pending(
        self,
        upload_id: UUID,
        claim: _ClaimReader,
        *,
        reason: str,
    ) -> None:
        """Record a retryable failure without claiming unverified cleanup progress."""
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        current_claim = claim()
        if current_claim.upload_id != upload_id:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        if (
            version.state is DocumentState.DELETED
            and version.index_state is DocumentIndexState.PURGED
            and version.retention_state is DocumentRetentionState.PURGED
        ):
            await self._metadata.enqueue_worker_event(
                self._event(
                    session,
                    version,
                    "document.deletion_effect_pending",
                    extra={"failure_type": reason},
                ),
                claim=current_claim,
            )
            return
        await self._metadata.enqueue_worker_event(
            self._event(
                session,
                version,
                "document.deletion_pending",
                extra={"failure_type": reason},
            ),
            claim=current_claim,
        )

    async def _tombstone(
        self,
        session: UploadSession,
        version: DocumentVersion,
        claim: _ClaimReader,
    ) -> tuple[UploadSession, DocumentVersion]:
        if version.state is DocumentState.DELETED:
            return session, version
        if version.index_state is DocumentIndexState.TOMBSTONED and version.retention_state in {
            DocumentRetentionState.TOMBSTONED,
            DocumentRetentionState.PURGE_PENDING,
        }:
            return session, version
        return await self._update_axes(
            session,
            version,
            claim=claim,
            session_updates={
                "index_state": DocumentIndexState.TOMBSTONED,
                "retention_state": DocumentRetentionState.TOMBSTONED,
            },
            version_updates={
                "active": False,
                "available": False,
                "index_state": DocumentIndexState.TOMBSTONED,
                "retention_state": DocumentRetentionState.TOMBSTONED,
            },
            action="document.tombstoned",
        )

    async def _set_purge_pending(
        self,
        session: UploadSession,
        version: DocumentVersion,
        claim: _ClaimReader,
    ) -> tuple[UploadSession, DocumentVersion]:
        if version.state is DocumentState.DELETED or version.retention_state in {
            DocumentRetentionState.PURGE_PENDING,
            DocumentRetentionState.PURGED,
        }:
            return session, version
        return await self._update_axes(
            session,
            version,
            claim=claim,
            session_updates={"retention_state": DocumentRetentionState.PURGE_PENDING},
            version_updates={"retention_state": DocumentRetentionState.PURGE_PENDING},
            action="document.purge_pending",
        )

    async def _advance_deleted(
        self,
        session: UploadSession,
        version: DocumentVersion,
        claim: _ClaimReader,
        *,
        actor_id: str,
        receipt: DocumentPurgeVerificationReceipt,
    ) -> tuple[UploadSession, DocumentVersion]:
        updates = {
            "index_state": DocumentIndexState.PURGED,
            "retention_state": DocumentRetentionState.PURGED,
        }
        state = (
            DocumentState.DELETED
            if version.state is DocumentState.DELETED
            else transition(version.state, DocumentState.DELETED)
        )
        updated_session = session.model_copy(
            update={**updates, "state": state, "revision": session.revision + 1}
        )
        updated_version = version.model_copy(
            update={
                **updates,
                "state": state,
                "active": False,
                "available": False,
                "updated_at": self._clock(),
                "revision": version.revision + 1,
            }
        )
        current_claim = claim()
        if current_claim.upload_id != session.upload_id:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        await self._metadata.transition_worker_stage(
            updated_session,
            updated_version,
            claim=current_claim,
            expected_upload_state=session.state.value,
            expected_upload_revision=session.revision,
            expected_version_state=version.state.value,
            expected_version_revision=version.revision,
            event=self._event(
                updated_session,
                updated_version,
                "document.deleted",
                actor_id=actor_id,
                extra={"purge_receipt": receipt.model_dump(mode="json")},
            ),
        )
        return updated_session, updated_version

    async def _update_axes(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        claim: _ClaimReader,
        session_updates: dict[str, object],
        version_updates: dict[str, object],
        action: str,
        extra: dict[str, object] | None = None,
    ) -> tuple[UploadSession, DocumentVersion]:
        updated_session = session.model_copy(
            update={**session_updates, "revision": session.revision + 1}
        )
        updated_version = version.model_copy(
            update={
                **version_updates,
                "updated_at": self._clock(),
                "revision": version.revision + 1,
            }
        )
        current_claim = claim()
        if current_claim.upload_id != session.upload_id:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        await self._metadata.transition_worker_stage(
            updated_session,
            updated_version,
            claim=current_claim,
            expected_upload_state=session.state.value,
            expected_upload_revision=session.revision,
            expected_version_state=version.state.value,
            expected_version_revision=version.revision,
            event=self._event(updated_session, updated_version, action, extra=extra),
        )
        return updated_session, updated_version

    async def _assert_active_claim(self, upload_id: UUID, claim: _ClaimReader) -> None:
        current_claim = claim()
        if current_claim.upload_id != upload_id:
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        await self._metadata.assert_worker_stage_active(current_claim)

    def _event(
        self,
        session: UploadSession,
        version: DocumentVersion,
        action: str,
        *,
        actor_id: str = "ingestion-worker",
        extra: dict[str, object] | None = None,
    ) -> DocumentLifecycleEvent:
        record: dict[str, object] = {
            "action": action,
            "actor_id": actor_id,
            "collection_id": session.collection_id,
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "upload_id": str(session.upload_id),
            "source_sha256": version.source_sha256,
            "state": version.state.value,
            "index_state": version.index_state.value,
            "retention_state": version.retention_state.value,
            "protection_state": version.protection_state.value,
            "sensitivity_label": version.sensitivity_label or "",
            "purposes": [purpose.value for purpose in version.purposes],
            "uploader_id": version.uploader_id,
            "failure_code": version.failure_code or "",
            "policy_version": version.retention.policy_version,
            "access_descriptor_ref": version.access.reference,
            "upload_revision": session.revision,
            "version_revision": version.revision,
        }
        if extra:
            record.update(extra)
        identity = f"{action}:{version.version_id}:{version.revision}"
        return DocumentLifecycleEvent(
            event_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
            idempotency_key=identity,
            topic="object.event",
            key=str(version.document_id),
            payload={
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "action": action,
                "event_type": action,
                "correlation_id": str(session.upload_id),
                "idempotency_key": identity,
                "resource_id": str(version.document_id),
                "resource_type": "document",
                "document_id": str(version.document_id),
                "record": record,
            },
            created_at=self._clock(),
        )
