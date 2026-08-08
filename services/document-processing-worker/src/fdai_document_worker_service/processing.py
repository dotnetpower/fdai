"""Fail-closed inspection, extraction, indexing, and deletion pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from fdai_service_contracts import (
    DocumentArtifactStore,
    DocumentDeletionRequest,
    DocumentEnvelope,
    DocumentExtractionUnavailableError,
    DocumentExtractor,
    DocumentIndex,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentReadyConsumer,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    MalwareScanner,
    MalwareVerdict,
    PromotableDocumentObjectStore,
    ProtectionInspector,
    ProtectionState,
    SourceStorageMode,
    UploadSession,
    WorkerDocumentObjectStore,
)

from fdai_document_worker_service.effects import (
    WorkerEffect,
    WorkerEffectKind,
    WorkerEffectStatus,
    WorkerMetadataStore,
)
from fdai_document_worker_service.state_machine import transition

_EXTRACTABLE_PROTECTION = frozenset(
    {
        ProtectionState.NONE,
        ProtectionState.LABELED_UNENCRYPTED,
        ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
    }
)
_LOGGER = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")
_ClaimReader = Callable[[], DocumentWorkerClaim]


class DocumentIngestionWorker:
    """Run mechanical document stages while preserving agent-owned gates."""

    def __init__(
        self,
        *,
        metadata: WorkerMetadataStore,
        objects: WorkerDocumentObjectStore,
        malware: MalwareScanner,
        protection: ProtectionInspector,
        extractor: DocumentExtractor,
        artifacts: DocumentArtifactStore,
        index: DocumentIndex,
        consumers: Iterable[DocumentReadyConsumer] = (),
        clock: Callable[[], datetime] | None = None,
        indexing_stage_timeout_seconds: float = 90.0,
    ) -> None:
        if indexing_stage_timeout_seconds <= 0:
            raise ValueError("indexing_stage_timeout_seconds MUST be positive")
        self._metadata = metadata
        self._objects = objects
        self._malware = malware
        self._protection = protection
        self._extractor = extractor
        self._artifacts = artifacts
        self._index = index
        self._consumers = {consumer.purpose: consumer for consumer in consumers}
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._indexing_stage_timeout_seconds = indexing_stage_timeout_seconds

    async def process(self, upload_id: UUID, claim: _ClaimReader) -> DocumentVersion:
        version = await self.inspect(upload_id, claim)
        if version.state in _TERMINAL_STATES:
            return version
        return await self.index(upload_id, claim)

    async def inspect(self, upload_id: UUID, claim: _ClaimReader) -> DocumentVersion:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state in _TERMINAL_STATES or version.state in {
            DocumentState.EXTRACTING,
            DocumentState.INDEXING,
        }:
            return version
        if version.state not in {
            DocumentState.RECEIVED,
            DocumentState.QUARANTINED,
            DocumentState.SCANNING,
            DocumentState.PROTECTION_CHECK,
        }:
            raise ValueError("worker cannot inspect the current document state")
        if version.state is DocumentState.RECEIVED:
            session, version = await self._advance(
                session, version, DocumentState.QUARANTINED, claim=claim
            )
        if version.state is DocumentState.QUARANTINED:
            session, version = await self._advance(
                session, version, DocumentState.SCANNING, claim=claim
            )
        if version.state is not DocumentState.SCANNING:
            return version
        try:
            malware_verdict = await self._malware.scan(self._objects.read(session.object_key))
        except Exception:  # noqa: BLE001 - mandatory scanner failure holds content
            malware_verdict = MalwareVerdict.UNAVAILABLE
        failure_code = _malware_failure(malware_verdict)
        inspection = None
        if failure_code is None:
            try:
                inspection = await self._protection.inspect(
                    source_name=session.source_name,
                    media_type_hint=session.media_type_hint,
                    chunks=self._objects.read(session.object_key),
                )
            except Exception:  # noqa: BLE001 - unknown protection never reaches extraction
                failure_code = "protection_check_unavailable"
        if inspection is not None and inspection.state not in _EXTRACTABLE_PROTECTION:
            failure_code = inspection.reason_code or inspection.state.value
        version = version.model_copy(
            update={
                "protection_state": inspection.state if inspection else ProtectionState.UNKNOWN,
                "observed_format": inspection.observed_format if inspection else None,
                "media_type": inspection.media_type if inspection else version.media_type,
                "sensitivity_label": inspection.sensitivity_label if inspection else None,
                "failure_code": failure_code,
                "updated_at": self._clock(),
            }
        )
        _session, version = await self._advance(
            session,
            version,
            DocumentState.PROTECTION_CHECK,
            claim=claim,
            action="document.inspected",
            extra={"malware_verdict": malware_verdict.value},
        )
        return version

    async def index(self, upload_id: UUID, claim: _ClaimReader) -> DocumentVersion:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state in _TERMINAL_STATES:
            return version
        if version.state is DocumentState.PROTECTION_CHECK:
            if version.failure_code or version.protection_state not in _EXTRACTABLE_PROTECTION:
                return await self._hold(
                    session,
                    version,
                    version.failure_code or version.protection_state.value,
                    claim,
                )
            if session.storage_mode is SourceStorageMode.METADATA_ONLY:
                session, version = await self._advance(
                    session,
                    version,
                    DocumentState.READY,
                    claim=claim,
                    version_updates={"active": True, "available": True},
                    action="document.ready",
                )
                return version
            session, version = await self._advance(
                session, version, DocumentState.EXTRACTING, claim=claim
            )
        if version.state not in {DocumentState.EXTRACTING, DocumentState.INDEXING}:
            raise ValueError("worker cannot index the current document state")
        prior_promotion = await self._metadata.get_worker_effect(
            upload_id, WorkerEffectKind.SOURCE_PROMOTION
        )
        if prior_promotion is not None:
            if not isinstance(self._objects, PromotableDocumentObjectStore):
                raise DocumentLifecycleConflictError(
                    "source promotion checkpoint requires a promotable object store"
                )
            await self._assert_active_claim(upload_id, claim)
            promoted_key = await self._objects.promote(session)
            if promoted_key != prior_promotion.object_key:
                raise DocumentLifecycleConflictError("source promotion target changed")
            session = session.model_copy(update={"object_key": promoted_key})
        try:
            envelope = await self._extractor.extract(
                version=version,
                chunks=self._objects.read(session.object_key),
            )
        except DocumentExtractionUnavailableError as exc:
            return await self._fail(session, version, exc.reason.value, claim)
        except Exception:  # noqa: BLE001 - parser details must not leak
            return await self._fail(session, version, "extraction_failed", claim)
        if version.state is DocumentState.EXTRACTING:
            session, version = await self._advance(
                session, version, DocumentState.INDEXING, claim=claim
            )
        try:
            await self._assert_active_claim(upload_id, claim)
            await self._run_stage("artifact_put", upload_id, self._artifacts.put(envelope))
            await self._assert_active_claim(upload_id, claim)
            await self._run_stage("index_commit", upload_id, self._index.commit(envelope))
            await self._assert_active_claim(upload_id, claim)
            consumer_warnings = await self._run_stage(
                "consumer_delivery", upload_id, self._consume(session, envelope)
            )
        except DocumentWorkerClaimConflictError:
            raise
        except Exception:  # noqa: BLE001 - partially indexed content never becomes available
            await self._index.delete(version.document_id, version.version_id)
            await self._artifacts.delete(version.document_id, version.version_id)
            return await self._fail(session, version, "indexing_failed", claim)
        session_updates: dict[str, object] = {}
        promotion_effect: WorkerEffect | None = prior_promotion
        if session.storage_mode is SourceStorageMode.MANAGED_COPY and isinstance(
            self._objects, PromotableDocumentObjectStore
        ):
            source_session = session
            await self._assert_active_claim(upload_id, claim)
            target_key = self._objects.governed_key(session)
            if promotion_effect is None:
                promotion_effect = await self._metadata.prepare_worker_effect(
                    claim=claim(),
                    kind=WorkerEffectKind.SOURCE_PROMOTION,
                    document_id=version.document_id,
                    version_id=version.version_id,
                    object_key=target_key,
                )
            promoted_key = await self._objects.promote(source_session)
            if promoted_key != promotion_effect.object_key:
                raise DocumentLifecycleConflictError("source promotion target changed")
            session_updates["object_key"] = promoted_key
        warnings = envelope.warnings + consumer_warnings
        target = DocumentState.READY_WITH_WARNINGS if warnings else DocumentState.READY
        cleanup_effect: WorkerEffect | None = None
        if session.storage_mode is SourceStorageMode.EPHEMERAL_PROCESSING:
            await self._assert_active_claim(upload_id, claim)
            cleanup_effect = await self._metadata.prepare_worker_effect(
                claim=claim(),
                kind=WorkerEffectKind.EPHEMERAL_SOURCE_CLEANUP,
                document_id=version.document_id,
                version_id=version.version_id,
                object_key=session.object_key,
            )
        try:
            session, version = await self._advance(
                session,
                version,
                target,
                claim=claim,
                session_updates=session_updates,
                version_updates={
                    "active": True,
                    "available": True,
                    "warnings": warnings,
                },
                action="document.ready",
            )
        except DocumentWorkerClaimConflictError:
            raise
        except DocumentLifecycleConflictError:
            await self._index.delete(version.document_id, version.version_id)
            await self._artifacts.delete(version.document_id, version.version_id)
            raise
        if promotion_effect is not None:
            await self._metadata.complete_worker_effect(promotion_effect.effect_id)
        if cleanup_effect is not None:
            await self._assert_active_claim(upload_id, claim)
            await self._objects.delete(cleanup_effect.object_key)
            await self._metadata.complete_worker_effect(cleanup_effect.effect_id)
        return version

    async def reconcile_effect(self, effect: WorkerEffect) -> None:
        """Converge one pending idempotent effect from authoritative lifecycle state."""
        if effect.status is WorkerEffectStatus.COMPLETED:
            return
        session = await self._metadata.get_upload(effect.upload_id)
        version = await self._metadata.get_version(effect.document_id, effect.version_id)
        if (
            session.document_id != effect.document_id
            or session.version_id != effect.version_id
            or version.upload_id != effect.upload_id
        ):
            raise DocumentLifecycleConflictError("worker effect identity no longer matches")
        ready_states = {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
        deletion_states = {DocumentState.DELETING, DocumentState.DELETED}
        if effect.kind is WorkerEffectKind.SOURCE_PROMOTION:
            if version.state in ready_states and session.object_key == effect.object_key:
                await self._metadata.complete_worker_effect(effect.effect_id)
                return
            if version.state in ready_states | deletion_states:
                await self._objects.delete(effect.object_key)
                await self._metadata.complete_worker_effect(effect.effect_id)
                return
            if version.state is DocumentState.INDEXING:
                return
        elif effect.kind is WorkerEffectKind.EPHEMERAL_SOURCE_CLEANUP:
            if version.state in ready_states | deletion_states:
                await self._objects.delete(effect.object_key)
                await self._metadata.complete_worker_effect(effect.effect_id)
                return
            if version.state is DocumentState.INDEXING:
                return
        raise DocumentLifecycleConflictError(
            "worker effect cannot be reconciled from the current lifecycle state"
        )

    async def apply_safety_decision(
        self, upload_id: UUID, claim: _ClaimReader, *, decision: str, reason: str
    ) -> DocumentVersion:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state is not DocumentState.PROTECTION_CHECK:
            if version.state in _TERMINAL_STATES:
                return version
            raise ValueError("safety decision requires protection_check state")
        if decision != "admit":
            return await self._hold(session, version, reason or "safety_hold", claim)
        return await self.index(upload_id, claim)

    async def republish_received(self, upload_id: UUID) -> None:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state is DocumentState.RECEIVED:
            await self._metadata.enqueue_event(
                self._event(
                    session,
                    version,
                    "document.received",
                    actor_id="ingestion-reconciler",
                )
            )

    async def republish_inspection(self, upload_id: UUID) -> None:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        if version.state is not DocumentState.PROTECTION_CHECK:
            return
        malware_verdict = "clean"
        if version.failure_code == "malware_detected":
            malware_verdict = "infected"
        elif version.failure_code == "malware_scanner_unavailable":
            malware_verdict = "unavailable"
        await self._metadata.enqueue_event(
            self._event(
                session,
                version,
                "document.inspected",
                actor_id="ingestion-reconciler",
                extra={"malware_verdict": malware_verdict},
            )
        )

    async def apply_deletion_request(
        self, request: DocumentDeletionRequest, claim: _ClaimReader
    ) -> DocumentVersion:
        """Delete artifacts only while the API-requested lifecycle revision is current."""
        version = await self._metadata.get_version(request.document_id, request.version_id)
        session = await self._metadata.get_upload(request.upload_id)
        if (
            session.document_id != request.document_id
            or session.version_id != request.version_id
            or session.state is not DocumentState.DELETING
            or version.state is not DocumentState.DELETING
            or session.revision != request.expected_upload_revision
            or version.revision != request.expected_version_revision
        ):
            raise DocumentLifecycleConflictError("stale document deletion request")
        effect = await self._metadata.prepare_worker_effect(
            claim=claim(),
            kind=WorkerEffectKind.DELETION_CLEANUP,
            document_id=request.document_id,
            version_id=request.version_id,
            object_key=session.object_key,
        )
        try:
            version = await self._complete_deletion_cleanup(
                effect,
                session,
                version,
                claim,
                actor_id=request.requested_by,
            )
        except DocumentWorkerClaimConflictError:
            raise
        except Exception as exc:
            current_claim = claim()
            if current_claim.upload_id != request.upload_id:
                raise DocumentWorkerClaimConflictError("document worker claim conflict") from exc
            await self._metadata.enqueue_worker_event(
                self._event(session, version, "document.deletion_pending"),
                claim=current_claim,
            )
            raise
        return version

    async def reconcile_deletion_effect(
        self,
        upload_id: UUID,
        claim: _ClaimReader,
        *,
        effect: WorkerEffect,
    ) -> DocumentVersion:
        """Resume one deletion intent under a newly acquired deletion-stage claim."""
        if effect.upload_id != upload_id or effect.kind is not WorkerEffectKind.DELETION_CLEANUP:
            raise DocumentLifecycleConflictError("invalid deletion cleanup effect")
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(effect.document_id, effect.version_id)
        if (
            session.document_id != effect.document_id
            or session.version_id != effect.version_id
            or version.upload_id != upload_id
            or session.state not in {DocumentState.DELETING, DocumentState.DELETED}
            or version.state not in {DocumentState.DELETING, DocumentState.DELETED}
        ):
            raise DocumentLifecycleConflictError(
                "deletion cleanup effect no longer matches lifecycle state"
            )
        return await self._complete_deletion_cleanup(
            effect,
            session,
            version,
            claim,
            actor_id="ingestion-reconciler",
        )

    async def _complete_deletion_cleanup(
        self,
        effect: WorkerEffect,
        session: UploadSession,
        version: DocumentVersion,
        claim: _ClaimReader,
        *,
        actor_id: str,
    ) -> DocumentVersion:
        if effect.object_key != session.object_key:
            raise DocumentLifecycleConflictError("deletion cleanup source target changed")
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
        if version.state is DocumentState.DELETING:
            _session, version = await self._advance(
                session,
                version,
                DocumentState.DELETED,
                claim=claim,
                version_updates={"available": False, "active": False},
                action="document.deleted",
                actor_id=actor_id,
            )
        await self._metadata.complete_worker_effect(effect.effect_id)
        return version

    async def _run_stage(
        self, stage: str, upload_id: UUID, operation: Awaitable[_ResultT]
    ) -> _ResultT:
        try:
            async with asyncio.timeout(self._indexing_stage_timeout_seconds):
                return await operation
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

    async def _advance(
        self,
        session: UploadSession,
        version: DocumentVersion,
        target: DocumentState,
        *,
        claim: _ClaimReader,
        session_updates: dict[str, object] | None = None,
        version_updates: dict[str, object] | None = None,
        action: str | None = None,
        actor_id: str = "ingestion-worker",
        extra: dict[str, object] | None = None,
    ) -> tuple[UploadSession, DocumentVersion]:
        state = transition(version.state, target)
        updated_session = session.model_copy(
            update={
                **(session_updates or {}),
                "state": state,
                "revision": session.revision + 1,
            }
        )
        updated_version = version.model_copy(
            update={
                **(version_updates or {}),
                "state": state,
                "updated_at": self._clock(),
                "revision": version.revision + 1,
            }
        )
        event_action = action or f"document.{state.value}"
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
                event_action,
                actor_id=actor_id,
                extra=extra,
            ),
        )
        return updated_session, updated_version

    async def _hold(
        self,
        session: UploadSession,
        version: DocumentVersion,
        reason: str,
        claim: _ClaimReader,
    ) -> DocumentVersion:
        session, version = await self._advance(
            session,
            version,
            DocumentState.HELD,
            claim=claim,
            session_updates={"failure_code": reason},
            version_updates={"failure_code": reason, "available": False},
            action="document.held",
        )
        return version

    async def _fail(
        self,
        session: UploadSession,
        version: DocumentVersion,
        reason: str,
        claim: _ClaimReader,
    ) -> DocumentVersion:
        session, version = await self._advance(
            session,
            version,
            DocumentState.FAILED,
            claim=claim,
            session_updates={"failure_code": reason},
            version_updates={"failure_code": reason, "available": False},
            action="document.failed",
        )
        return version

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
        record = self._payload(session, version, action, actor_id, extra)
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

    @staticmethod
    def _payload(
        session: UploadSession,
        version: DocumentVersion,
        action: str,
        actor_id: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "action": action,
            "actor_id": actor_id,
            "collection_id": session.collection_id,
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "source_sha256": version.source_sha256,
            "state": version.state.value,
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
        return record


_TERMINAL_STATES = frozenset(
    {
        DocumentState.READY,
        DocumentState.READY_WITH_WARNINGS,
        DocumentState.HELD,
        DocumentState.FAILED,
        DocumentState.DELETED,
    }
)


def _malware_failure(verdict: MalwareVerdict) -> str | None:
    if verdict is MalwareVerdict.INFECTED:
        return "malware_detected"
    if verdict is not MalwareVerdict.CLEAN:
        return "malware_scanner_unavailable"
    return None
