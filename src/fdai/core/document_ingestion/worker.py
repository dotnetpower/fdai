"""Fail-closed worker for scan, protection, extraction, index, and deletion."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from fdai.core.document_ingestion.state_machine import transition
from fdai.shared.contracts import (
    DocumentEnvelope,
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
    DocumentReadyConsumer,
    MalwareScanner,
    PromotableDocumentObjectStore,
    ProtectionInspector,
)

_EXTRACTABLE_PROTECTION = frozenset(
    {
        ProtectionState.NONE,
        ProtectionState.LABELED_UNENCRYPTED,
        ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
    }
)
_LOGGER = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")


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
        consumers: Iterable[DocumentReadyConsumer] = (),
        clock: Callable[[], datetime] | None = None,
        indexing_stage_timeout_seconds: float = 90.0,
    ) -> None:
        if indexing_stage_timeout_seconds <= 0:
            raise ValueError("indexing_stage_timeout_seconds MUST be positive")
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._malware = malware
        self._protection = protection
        self._extractor = extractor
        self._artifacts = artifacts
        self._index = index
        self._activity = activity
        self._consumers = {consumer.purpose: consumer for consumer in consumers}
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._indexing_stage_timeout_seconds = indexing_stage_timeout_seconds

    async def process(self, upload_id: UUID) -> DocumentVersion:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state in {
            DocumentState.READY,
            DocumentState.READY_WITH_WARNINGS,
            DocumentState.HELD,
            DocumentState.FAILED,
            DocumentState.DELETED,
        }:
            return version
        if version.state not in {
            DocumentState.RECEIVED,
            DocumentState.QUARANTINED,
            DocumentState.SCANNING,
            DocumentState.PROTECTION_CHECK,
            DocumentState.EXTRACTING,
            DocumentState.INDEXING,
        }:
            raise ValueError("worker cannot process the current document state")

        if version.state is DocumentState.RECEIVED:
            session, version = await self._advance(session, version, DocumentState.QUARANTINED)
        if version.state is DocumentState.QUARANTINED:
            session, version = await self._advance(session, version, DocumentState.SCANNING)
        if version.state is DocumentState.SCANNING:
            try:
                verdict = await self._malware.scan(self._objects.read(session.object_key))
            except Exception:  # noqa: BLE001 - mandatory provider failures hold content
                return await self._hold(session, version, "malware_scanner_unavailable")
            if verdict is MalwareVerdict.INFECTED:
                return await self._hold(session, version, "malware_detected")
            if verdict is not MalwareVerdict.CLEAN:
                return await self._hold(session, version, "malware_scanner_unavailable")
            session, version = await self._advance(session, version, DocumentState.PROTECTION_CHECK)
        if version.state is DocumentState.PROTECTION_CHECK:
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
        if version.state is DocumentState.EXTRACTING:
            session, version = await self._advance(session, version, DocumentState.INDEXING)
        try:
            await self._run_indexing_stage(
                "artifact_put", session.upload_id, self._artifacts.put(envelope)
            )
            await self._run_indexing_stage(
                "index_commit", session.upload_id, self._index.commit(envelope)
            )
            consumer_warnings = await self._run_indexing_stage(
                "consumer_delivery", session.upload_id, self._consume(session, envelope)
            )
        except Exception:  # noqa: BLE001 - no partially indexed document becomes available
            await self._index.delete(version.document_id, version.version_id)
            await self._artifacts.delete(version.document_id, version.version_id)
            return await self._fail(session, version, "indexing_failed")

        if session.storage_mode is SourceStorageMode.MANAGED_COPY and isinstance(
            self._objects, PromotableDocumentObjectStore
        ):
            source_session = session
            promoted_key = self._objects.governed_key(session)
            session = session.model_copy(update={"object_key": promoted_key})
            await self._metadata.save_upload(session)
            try:
                await self._objects.promote(source_session)
            except Exception:
                await self._metadata.save_upload(source_session)
                raise

        warnings = envelope.warnings + consumer_warnings
        target = DocumentState.READY_WITH_WARNINGS if warnings else DocumentState.READY
        session, version = await self._advance(session, version, target)
        version = version.model_copy(
            update={
                "active": True,
                "available": True,
                "warnings": warnings,
                "updated_at": self._clock(),
            }
        )
        await self._metadata.save_version(version)
        await self._record(session, version, "document.ready")
        if session.storage_mode is SourceStorageMode.EPHEMERAL_PROCESSING:
            await self._objects.delete(session.object_key)
        return version

    async def _run_indexing_stage(
        self,
        stage: str,
        upload_id: UUID,
        operation: Awaitable[_ResultT],
    ) -> _ResultT:
        try:
            async with asyncio.timeout(self._indexing_stage_timeout_seconds):
                return await operation
        except TimeoutError:
            _LOGGER.error(
                "document_ingestion_stage_timeout",
                extra={
                    "upload_id": str(upload_id),
                    "stage": stage,
                    "timeout_seconds": self._indexing_stage_timeout_seconds,
                },
            )
            raise
        except Exception as exc:
            _LOGGER.error(
                "document_ingestion_stage_failed",
                extra={
                    "upload_id": str(upload_id),
                    "stage": stage,
                    "exception_type": type(exc).__name__,
                },
            )
            raise

    async def _consume(self, session: UploadSession, envelope: DocumentEnvelope) -> tuple[str, ...]:
        warnings: list[str] = []
        for purpose in envelope.purposes:
            consumer = self._consumers.get(purpose)
            if consumer is not None:
                warnings.extend(await consumer.consume(session=session, envelope=envelope))
        return tuple(warnings)

    async def delete(
        self,
        *,
        actor_id: str,
        document_id: UUID,
        version_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> DocumentVersion:
        version = await self._metadata.get_version(document_id, version_id)
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
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
