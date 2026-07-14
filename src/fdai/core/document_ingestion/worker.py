"""Fail-closed worker for scan, protection, extraction, index, and deletion."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fdai.core.document_ingestion.state_machine import transition
from fdai.shared.contracts import (
    DocumentState,
    DocumentVersion,
    MalwareVerdict,
    ProtectionState,
    SourceStorageMode,
    UploadSession,
)
from fdai.shared.providers.document_ingestion import (
    DocumentAccessProvider,
    DocumentActivitySink,
    DocumentArtifactStore,
    DocumentExtractor,
    DocumentIndex,
    DocumentMetadataStore,
    DocumentObjectStore,
    MalwareScanner,
    ProtectionInspector,
)

_EXTRACTABLE_PROTECTION = frozenset(
    {
        ProtectionState.NONE,
        ProtectionState.LABELED_UNENCRYPTED,
        ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
    }
)


class DocumentIngestionWorker:
    """Runs one document version through mandatory safety stages."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentMetadataStore,
        objects: DocumentObjectStore,
        malware: MalwareScanner,
        protection: ProtectionInspector,
        extractor: DocumentExtractor,
        artifacts: DocumentArtifactStore,
        index: DocumentIndex,
        activity: DocumentActivitySink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._malware = malware
        self._protection = protection
        self._extractor = extractor
        self._artifacts = artifacts
        self._index = index
        self._activity = activity
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def process(self, upload_id: UUID) -> DocumentVersion:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state is not DocumentState.RECEIVED:
            raise ValueError("worker accepts only received document versions")

        session, version = await self._advance(session, version, DocumentState.QUARANTINED)
        session, version = await self._advance(session, version, DocumentState.SCANNING)
        try:
            verdict = await self._malware.scan(self._objects.read(session.object_key))
        except Exception:  # noqa: BLE001 - mandatory provider failures hold content
            return await self._hold(session, version, "malware_scanner_unavailable")
        if verdict is MalwareVerdict.INFECTED:
            return await self._hold(session, version, "malware_detected")
        if verdict is not MalwareVerdict.CLEAN:
            return await self._hold(session, version, "malware_scanner_unavailable")

        session, version = await self._advance(session, version, DocumentState.PROTECTION_CHECK)
        try:
            inspection = await self._protection.inspect(
                source_name=session.source_name,
                media_type_hint=session.media_type_hint,
                chunks=self._objects.read(session.object_key),
            )
        except Exception:  # noqa: BLE001 - unknown protection never reaches extraction
            return await self._hold(session, version, "protection_check_unavailable")
        version = version.model_copy(
            update={
                "protection_state": inspection.state,
                "observed_format": inspection.observed_format,
                "media_type": inspection.media_type,
                "sensitivity_label": inspection.sensitivity_label,
                "updated_at": self._clock(),
            }
        )
        await self._metadata.save_version(version)
        if inspection.state not in _EXTRACTABLE_PROTECTION:
            return await self._hold(
                session, version, inspection.reason_code or inspection.state.value
            )
        if session.storage_mode is SourceStorageMode.METADATA_ONLY:
            session, version = await self._advance(session, version, DocumentState.READY)
            version = version.model_copy(update={"active": True, "available": True})
            await self._metadata.save_version(version)
            await self._record(session, version, "document.ready")
            return version

        session, version = await self._advance(session, version, DocumentState.EXTRACTING)
        try:
            envelope = await self._extractor.extract(
                version=version, chunks=self._objects.read(session.object_key)
            )
        except Exception:  # noqa: BLE001 - parser details must not leak
            return await self._fail(session, version, "extraction_failed")
        session, version = await self._advance(session, version, DocumentState.INDEXING)
        try:
            await self._artifacts.put(envelope)
            await self._index.commit(envelope)
        except Exception:  # noqa: BLE001 - no partially indexed document becomes available
            await self._index.delete(version.document_id, version.version_id)
            await self._artifacts.delete(version.document_id, version.version_id)
            return await self._fail(session, version, "indexing_failed")

        target = DocumentState.READY_WITH_WARNINGS if envelope.warnings else DocumentState.READY
        session, version = await self._advance(session, version, target)
        version = version.model_copy(
            update={
                "active": True,
                "available": True,
                "warnings": envelope.warnings,
                "updated_at": self._clock(),
            }
        )
        await self._metadata.save_version(version)
        await self._record(session, version, "document.ready")
        if session.storage_mode is SourceStorageMode.EPHEMERAL_PROCESSING:
            await self._objects.delete(session.object_key)
        return version

    async def delete(
        self, *, actor_id: str, document_id: UUID, version_id: UUID
    ) -> DocumentVersion:
        version = await self._metadata.get_version(document_id, version_id)
        await self._access.authorize_delete(actor_id=actor_id, version=version)
        if version.retention.legal_hold:
            raise ValueError("document version is subject to legal hold")
        session = await self._metadata.get_upload(version.upload_id)
        session, version = await self._advance(session, version, DocumentState.DELETING)
        version = version.model_copy(update={"available": False, "active": False})
        await self._metadata.save_version(version)
        try:
            await self._index.delete(document_id, version_id)
            await self._artifacts.delete(document_id, version_id)
            await self._objects.delete(session.object_key)
        except Exception:
            await self._record(session, version, "document.deletion_pending")
            raise
        session, version = await self._advance(session, version, DocumentState.DELETED)
        await self._record(session, version, "document.deleted", actor_id=actor_id)
        return version

    async def _advance(
        self, session: UploadSession, version: DocumentVersion, target: DocumentState
    ) -> tuple[UploadSession, DocumentVersion]:
        state = transition(version.state, target)
        session = session.model_copy(update={"state": state})
        version = version.model_copy(update={"state": state, "updated_at": self._clock()})
        await self._metadata.save_upload(session)
        await self._metadata.save_version(version)
        return session, version

    async def _hold(
        self, session: UploadSession, version: DocumentVersion, reason: str
    ) -> DocumentVersion:
        session, version = await self._advance(session, version, DocumentState.HELD)
        version = version.model_copy(update={"failure_code": reason, "available": False})
        session = session.model_copy(update={"failure_code": reason})
        await self._metadata.save_version(version)
        await self._metadata.save_upload(session)
        await self._record(session, version, "document.held")
        return version

    async def _fail(
        self, session: UploadSession, version: DocumentVersion, reason: str
    ) -> DocumentVersion:
        session, version = await self._advance(session, version, DocumentState.FAILED)
        version = version.model_copy(update={"failure_code": reason, "available": False})
        session = session.model_copy(update={"failure_code": reason})
        await self._metadata.save_version(version)
        await self._metadata.save_upload(session)
        await self._record(session, version, "document.failed")
        return version

    async def _record(
        self,
        session: UploadSession,
        version: DocumentVersion,
        action: str,
        *,
        actor_id: str = "ingestion-worker",
    ) -> None:
        record: dict[str, object] = {
            "action": action,
            "actor_id": actor_id,
            "collection_id": session.collection_id,
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "source_sha256": version.source_sha256,
            "state": version.state.value,
            "protection_state": version.protection_state.value,
            "failure_code": version.failure_code or "",
            "policy_version": version.retention.policy_version,
            "access_descriptor_ref": version.access.reference,
        }
        await self._activity.audit(record)
        await self._activity.publish(action, str(version.document_id), record)


__all__ = ["DocumentIngestionWorker"]
