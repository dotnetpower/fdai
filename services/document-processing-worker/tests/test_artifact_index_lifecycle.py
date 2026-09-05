from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_document_worker_service.artifact_manifest import build_artifact_manifest
from fdai_document_worker_service.effects import (
    WorkerEffect,
    WorkerEffectKind,
    WorkerEffectStatus,
    worker_effect_id,
)
from fdai_document_worker_service.processing import DocumentIngestionWorker
from fdai_document_worker_service.purge import PurgeVerificationError
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentArtifactKind,
    DocumentDeletionRequest,
    DocumentEnvelope,
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentPurgeVerificationReceipt,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    StructuralUnit,
    UploadSession,
)

NOW = datetime(2026, 9, 5, 5, 45, tzinfo=UTC)
CONTENT = b"native text"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def _records(
    state: DocumentState,
    *,
    index_state: DocumentIndexState = DocumentIndexState.NOT_REQUESTED,
    retention_state: DocumentRetentionState = DocumentRetentionState.LIVE,
    legal_hold: bool = False,
) -> tuple[UploadSession, DocumentVersion]:
    access = AccessDescriptor(reference="policy", collection_id="knowledge")
    retention = RetentionPolicy(
        policy_version="retention-v1",
        source_expires_at=NOW + timedelta(days=30),
        derived_expires_at=NOW + timedelta(days=7),
        legal_hold=legal_hold,
    )
    session = UploadSession(
        upload_id=UUID(int=1),
        document_id=UUID(int=2),
        version_id=UUID(int=3),
        actor_id="operator",
        source_name="source.pdf",
        collection_id="knowledge",
        object_key="source/object",
        media_type_hint="application/pdf",
        expected_size=len(CONTENT),
        expected_sha256=DIGEST,
        state=state,
        storage_mode=SourceStorageMode.LINKED_SOURCE,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        access=access,
        retention=retention,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        index_state=index_state,
        retention_state=retention_state,
    )
    version = DocumentVersion(
        document_id=session.document_id,
        version_id=session.version_id,
        upload_id=session.upload_id,
        source_name=session.source_name,
        source_sha256=DIGEST,
        size_bytes=len(CONTENT),
        media_type="application/pdf",
        observed_format="pdf",
        state=state,
        protection_state=ProtectionState.NONE,
        access=access,
        retention=retention,
        purposes=session.purposes,
        uploader_id="operator",
        created_at=NOW,
        updated_at=NOW,
        active=state is DocumentState.DELETING,
        available=state is DocumentState.DELETING,
        index_state=index_state,
        retention_state=retention_state,
    )
    return session, version


def _envelope(version: DocumentVersion) -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id=version.document_id,
        version_id=version.version_id,
        source_sha256=version.source_sha256,
        media_type=version.media_type,
        observed_format="pdf",
        size_bytes=version.size_bytes,
        collection_id=version.access.collection_id,
        purposes=version.purposes,
        protection_state=version.protection_state,
        access_descriptor_ref=version.access.reference,
        units=(
            StructuralUnit(
                unit_id="native",
                kind="page",
                locator="pdf/page:1/block:1",
                text="native text",
            ),
            StructuralUnit(
                unit_id="ocr",
                kind="page",
                locator="pdf/page:2/ocr:1",
                text="scanned text",
            ),
        ),
        extractor_name="test-extractor",
        extractor_version="1.2.3",
    )


def test_manifest_rejects_missing_unit_parent_without_fabricating_lineage() -> None:
    _session, version = _records(DocumentState.EXTRACTING)
    envelope = _envelope(version).model_copy(
        update={
            "units": (
                StructuralUnit(
                    unit_id="child",
                    kind="paragraph",
                    locator="pdf/page:1/block:2",
                    parent_locator="missing",
                    text="child",
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="parent locator does not exist"):
        build_artifact_manifest(envelope=envelope, version=version, observed_at=NOW)


class MemoryMetadata:
    def __init__(self, session: UploadSession, version: DocumentVersion) -> None:
        self.session = session
        self.version = version
        self.events: list[DocumentLifecycleEvent] = []
        self.effects: dict[UUID, WorkerEffect] = {}
        self.transitions: list[
            tuple[DocumentState, DocumentIndexState, DocumentRetentionState]
        ] = []

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        assert upload_id == self.session.upload_id
        return self.session

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        assert (document_id, version_id) == (self.version.document_id, self.version.version_id)
        return self.version

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
        assert claim.upload_id == session.upload_id
        if (
            self.session.state.value != expected_upload_state
            or self.session.revision != expected_upload_revision
            or self.version.state.value != expected_version_state
            or self.version.revision != expected_version_revision
        ):
            raise DocumentLifecycleConflictError("test CAS conflict")
        self.session = session
        self.version = version
        self.events.append(event)
        self.transitions.append((version.state, version.index_state, version.retention_state))

    async def assert_worker_stage_active(self, claim: DocumentWorkerClaim) -> None:
        assert claim.upload_id == self.session.upload_id
        assert claim.status is DocumentWorkerClaimStatus.ACTIVE

    async def prepare_worker_effect(
        self,
        *,
        claim: DocumentWorkerClaim,
        kind: WorkerEffectKind,
        document_id: UUID,
        version_id: UUID,
        object_key: str,
    ) -> WorkerEffect:
        effect_id = worker_effect_id(kind, version_id)
        effect = self.effects.get(effect_id)
        if effect is None:
            effect = WorkerEffect(
                effect_id=effect_id,
                upload_id=claim.upload_id,
                document_id=document_id,
                version_id=version_id,
                kind=kind,
                object_key=object_key,
                status=WorkerEffectStatus.PENDING,
                created_at=NOW,
            )
            self.effects[effect_id] = effect
        return effect

    async def get_worker_effect(
        self, upload_id: UUID, kind: WorkerEffectKind
    ) -> WorkerEffect | None:
        return next(
            (
                effect
                for effect in self.effects.values()
                if effect.upload_id == upload_id and effect.kind is kind
            ),
            None,
        )

    async def complete_worker_effect(self, effect_id: UUID) -> None:
        self.effects[effect_id] = self.effects[effect_id].model_copy(
            update={"status": WorkerEffectStatus.COMPLETED, "completed_at": NOW}
        )

    async def enqueue_worker_event(
        self, event: DocumentLifecycleEvent, *, claim: DocumentWorkerClaim
    ) -> None:
        assert claim.upload_id == self.session.upload_id
        self.events.append(event)


class FailOnceEffectCompletionMetadata(MemoryMetadata):
    def __init__(self, session: UploadSession, version: DocumentVersion) -> None:
        super().__init__(session, version)
        self.fail_completion = True

    async def complete_worker_effect(self, effect_id: UUID) -> None:
        if self.fail_completion:
            self.fail_completion = False
            raise RuntimeError("injected effect completion crash")
        await super().complete_worker_effect(effect_id)


class MemoryObjects:
    def __init__(self, order: list[str]) -> None:
        self.content = {"source/object": CONTENT}
        self.order = order

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        yield self.content[object_key]

    async def delete(self, object_key: str) -> None:
        self.order.append("source")
        self.content.pop(object_key, None)


class RecordingArtifacts:
    def __init__(self, order: list[str], *, fail_once: bool = False) -> None:
        self.order = order
        self.fail_once = fail_once
        self.envelope: DocumentEnvelope | None = None

    async def put(self, envelope: DocumentEnvelope) -> str:
        self.envelope = envelope
        return "artifact"

    async def delete(self, _document_id: UUID, _version_id: UUID) -> None:
        self.order.append("artifacts")
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("injected artifact failure")
        self.envelope = None


class RecordingIndex:
    def __init__(self, order: list[str], *, fail_commit: bool = False) -> None:
        self.order = order
        self.fail_commit = fail_commit
        self.active = False
        self.staged = False

    async def commit(self, _envelope: DocumentEnvelope) -> int:
        if self.fail_commit:
            raise RuntimeError("injected index failure")
        self.staged = True
        return 2

    async def activate(self, _document_id: UUID, _version_id: UUID) -> None:
        self.staged = False
        self.active = True

    async def tombstone(self, _document_id: UUID, _version_id: UUID) -> None:
        self.order.append("tombstone")
        self.active = False

    async def delete(self, _document_id: UUID, _version_id: UUID) -> None:
        self.order.append("index")
        self.active = False


class StaticExtractor:
    def __init__(self, envelope: DocumentEnvelope) -> None:
        self.envelope = envelope

    async def extract(
        self, *, version: DocumentVersion, chunks: AsyncIterator[bytes]
    ) -> DocumentEnvelope:
        del version
        _ = b"".join([chunk async for chunk in chunks])
        return self.envelope


class ReceiptVerifier:
    def __init__(
        self,
        order: list[str],
        *,
        receipts: Sequence[DocumentPurgeVerificationReceipt] = (),
        failures: int = 0,
    ) -> None:
        self.order = order
        self.receipts = list(receipts)
        self.failures = failures

    async def verify(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_object_keys: Sequence[str],
    ) -> DocumentPurgeVerificationReceipt:
        assert source_object_keys == ("source/object",)
        self.order.append("verify")
        if self.failures:
            self.failures -= 1
            raise RuntimeError("injected verifier crash")
        return self.receipts.pop(0) if self.receipts else _receipt(document_id, version_id)


def _receipt(
    document_id: UUID,
    version_id: UUID,
    **updates: object,
) -> DocumentPurgeVerificationReceipt:
    values: dict[str, object] = {
        "document_id": document_id,
        "version_id": version_id,
        "live_index_rows": 0,
        "derivative_objects": 0,
        "source_objects": 0,
        "cache_entries": 0,
        "legal_hold_blocked": False,
        "backup_blocked": False,
        "verified_at": NOW,
    }
    values.update(updates)
    return DocumentPurgeVerificationReceipt.model_validate(values)


def _claim(upload_id: UUID) -> DocumentWorkerClaim:
    return DocumentWorkerClaim(
        upload_id=upload_id,
        stage=DocumentWorkerStage.INDEXING,
        owner="worker",
        attempt_id=UUID(int=4),
        revision=1,
        status=DocumentWorkerClaimStatus.ACTIVE,
        claimed_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )


def _worker(
    metadata: MemoryMetadata,
    objects: MemoryObjects,
    artifacts: RecordingArtifacts,
    index: RecordingIndex,
    *,
    verifier: ReceiptVerifier | None = None,
) -> DocumentIngestionWorker:
    return DocumentIngestionWorker(
        metadata=metadata,  # type: ignore[arg-type]
        objects=objects,
        malware=object(),  # type: ignore[arg-type]
        protection=object(),  # type: ignore[arg-type]
        extractor=StaticExtractor(_envelope(metadata.version)),
        artifacts=artifacts,
        index=index,
        purge_verifier=verifier,
        clock=lambda: NOW,
    )


def test_manifest_is_deterministic_and_records_discarded_pdf_and_office_images() -> None:
    _session, version = _records(DocumentState.EXTRACTING)
    envelope = _envelope(version)

    first = build_artifact_manifest(envelope=envelope, version=version, observed_at=NOW)
    second = build_artifact_manifest(envelope=envelope, version=version, observed_at=NOW)

    assert first == second
    assert sum(entry.kind is DocumentArtifactKind.SOURCE for entry in first.entries) == 1
    source = next(entry for entry in first.entries if entry.kind is DocumentArtifactKind.SOURCE)
    raster = next(
        entry for entry in first.entries if entry.kind is DocumentArtifactKind.PAGE_RASTER
    )
    ocr = next(entry for entry in first.entries if entry.kind is DocumentArtifactKind.OCR_TEXT)
    normalized = next(
        entry for entry in first.entries if entry.kind is DocumentArtifactKind.NORMALIZED_ENVELOPE
    )
    assert raster.retained is False
    assert ocr.parent_artifact_id == raster.artifact_id
    assert normalized.parent_artifact_id == source.artifact_id
    assert all(
        entry.content_sha256 is not None and len(entry.content_sha256) == 64
        for entry in first.entries
        if entry.retained
    )
    assert raster.content_sha256 is None
    assert raster.size_bytes is None
    assert all(
        not entry.retained
        or entry.kind is DocumentArtifactKind.SOURCE
        or entry.expires_at == version.retention.derived_expires_at
        for entry in first.entries
    )

    office = envelope.model_copy(
        update={
            "observed_format": "ooxml",
            "units": (
                StructuralUnit(
                    unit_id="image-ocr",
                    kind="page",
                    locator="ooxml/embedded-image:1/ocr:1",
                    text="image text",
                ),
            ),
            "warnings": ("embedded_images_without_text:1",),
        }
    )
    office_manifest = build_artifact_manifest(envelope=office, version=version, observed_at=NOW)
    image = next(
        entry
        for entry in office_manifest.entries
        if entry.kind is DocumentArtifactKind.EMBEDDED_IMAGE
    )
    office_ocr = next(
        entry for entry in office_manifest.entries if entry.kind is DocumentArtifactKind.OCR_TEXT
    )
    assert image.retained is False
    assert office_ocr.parent_artifact_id == image.artifact_id

    direct_image = envelope.model_copy(
        update={
            "observed_format": "image",
            "media_type": "image/png",
            "units": (
                StructuralUnit(
                    unit_id="image-line",
                    kind="page",
                    locator="page:1:line:1",
                    text="image text",
                ),
            ),
        }
    )
    image_manifest = build_artifact_manifest(
        envelope=direct_image,
        version=version,
        observed_at=NOW,
    )
    assert all(
        entry.kind is not DocumentArtifactKind.PAGE_RASTER for entry in image_manifest.entries
    )


async def test_index_transitions_and_manifest_precede_artifact_storage() -> None:
    session, version = _records(DocumentState.PROTECTION_CHECK)
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    artifacts = RecordingArtifacts(order)
    index = RecordingIndex(order)
    worker = _worker(metadata, MemoryObjects(order), artifacts, index)
    claim = _claim(session.upload_id)

    ready = await worker.index(session.upload_id, lambda: claim)

    assert [state[1] for state in metadata.transitions] == [
        DocumentIndexState.QUEUED,
        DocumentIndexState.BUILDING,
        DocumentIndexState.ACTIVE,
    ]
    assert ready.index_state is DocumentIndexState.ACTIVE
    assert metadata.session.index_state is DocumentIndexState.ACTIVE
    assert artifacts.envelope is not None
    assert artifacts.envelope.artifact_manifest is not None


async def test_index_failure_sets_failed_axis() -> None:
    session, version = _records(DocumentState.PROTECTION_CHECK)
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    worker = _worker(
        metadata,
        MemoryObjects(order),
        RecordingArtifacts(order),
        RecordingIndex(order, fail_commit=True),
    )
    claim = _claim(session.upload_id)

    failed = await worker.index(session.upload_id, lambda: claim)

    assert failed.state is DocumentState.FAILED
    assert failed.index_state is DocumentIndexState.FAILED
    assert metadata.session.index_state is DocumentIndexState.FAILED


async def test_deletion_orders_cleanup_and_purges_only_after_verified_receipt() -> None:
    session, version = _records(
        DocumentState.DELETING,
        index_state=DocumentIndexState.ACTIVE,
    )
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    verifier = ReceiptVerifier(order)
    worker = _worker(
        metadata,
        MemoryObjects(order),
        RecordingArtifacts(order),
        RecordingIndex(order),
        verifier=verifier,
    )
    claim = _claim(session.upload_id).model_copy(update={"stage": DocumentWorkerStage.DELETION})

    deleted = await worker.apply_deletion_request(_request(session, version), lambda: claim)

    assert order == ["tombstone", "index", "artifacts", "source", "verify"]
    assert metadata.transitions[0][1:] == (
        DocumentIndexState.TOMBSTONED,
        DocumentRetentionState.TOMBSTONED,
    )
    assert [transition[2] for transition in metadata.transitions] == [
        DocumentRetentionState.TOMBSTONED,
        DocumentRetentionState.PURGE_PENDING,
        DocumentRetentionState.PURGED,
    ]
    assert deleted.state is DocumentState.DELETED
    assert deleted.index_state is DocumentIndexState.PURGED
    assert deleted.retention_state is DocumentRetentionState.PURGED
    event = metadata.events[-1]
    record = event.payload["record"]
    assert isinstance(record, dict)
    receipt = record["purge_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["verified"] is True


async def test_partial_failure_is_pending_and_replay_converges() -> None:
    session, version = _records(
        DocumentState.DELETING,
        index_state=DocumentIndexState.ACTIVE,
    )
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    artifacts = RecordingArtifacts(order, fail_once=True)
    worker = _worker(
        metadata,
        MemoryObjects(order),
        artifacts,
        RecordingIndex(order),
        verifier=ReceiptVerifier(order),
    )
    claim = _claim(session.upload_id).model_copy(update={"stage": DocumentWorkerStage.DELETION})
    request = _request(session, version)

    with pytest.raises(RuntimeError, match="artifact failure"):
        await worker.apply_deletion_request(request, lambda: claim)

    assert metadata.version.retention_state is DocumentRetentionState.PURGE_PENDING
    effect = next(iter(metadata.effects.values()))
    assert effect.status is WorkerEffectStatus.PENDING

    deleted = await worker.reconcile_deletion_effect(
        session.upload_id,
        lambda: claim,
        effect=effect,
    )
    assert deleted.retention_state is DocumentRetentionState.PURGED
    assert metadata.effects[effect.effect_id].status is WorkerEffectStatus.COMPLETED
    assert order == [
        "tombstone",
        "index",
        "artifacts",
        "tombstone",
        "index",
        "artifacts",
        "source",
        "verify",
    ]


async def test_replay_after_verified_transition_only_completes_effect() -> None:
    session, version = _records(
        DocumentState.DELETING,
        index_state=DocumentIndexState.ACTIVE,
    )
    metadata = FailOnceEffectCompletionMetadata(session, version)
    order: list[str] = []
    worker = _worker(
        metadata,
        MemoryObjects(order),
        RecordingArtifacts(order),
        RecordingIndex(order),
        verifier=ReceiptVerifier(order),
    )
    claim = _claim(session.upload_id).model_copy(update={"stage": DocumentWorkerStage.DELETION})

    with pytest.raises(RuntimeError, match="completion crash"):
        await worker.apply_deletion_request(_request(session, version), lambda: claim)

    effect = next(iter(metadata.effects.values()))
    assert metadata.version.state is DocumentState.DELETED
    assert metadata.version.retention_state is DocumentRetentionState.PURGED
    assert effect.status is WorkerEffectStatus.PENDING
    completed_order = tuple(order)

    replayed = await worker.reconcile_deletion_effect(
        session.upload_id,
        lambda: claim,
        effect=effect,
    )

    assert replayed.retention_state is DocumentRetentionState.PURGED
    assert metadata.effects[effect.effect_id].status is WorkerEffectStatus.COMPLETED
    assert tuple(order) == completed_order


@pytest.mark.parametrize(
    "receipt_updates",
    (
        {"source_objects": 1},
        {"legal_hold_blocked": True},
        {"backup_blocked": True},
    ),
)
async def test_verifier_crash_and_rejection_never_mark_purged(
    receipt_updates: dict[str, object],
) -> None:
    session, version = _records(
        DocumentState.DELETING,
        index_state=DocumentIndexState.ACTIVE,
    )
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    rejected = _receipt(session.document_id, session.version_id, **receipt_updates)
    verifier = ReceiptVerifier(order, receipts=(rejected,), failures=1)
    worker = _worker(
        metadata,
        MemoryObjects(order),
        RecordingArtifacts(order),
        RecordingIndex(order),
        verifier=verifier,
    )
    claim = _claim(session.upload_id).model_copy(update={"stage": DocumentWorkerStage.DELETION})
    request = _request(session, version)

    with pytest.raises(RuntimeError, match="verifier crash"):
        await worker.apply_deletion_request(request, lambda: claim)
    effect = next(iter(metadata.effects.values()))
    with pytest.raises(PurgeVerificationError, match="residue"):
        await worker.reconcile_deletion_effect(
            session.upload_id,
            lambda: claim,
            effect=effect,
        )

    assert metadata.version.state is DocumentState.DELETING
    assert metadata.version.index_state is DocumentIndexState.TOMBSTONED
    assert metadata.version.retention_state is DocumentRetentionState.PURGE_PENDING
    assert metadata.effects[effect.effect_id].status is WorkerEffectStatus.PENDING


async def test_legal_hold_tombstones_index_before_blocking_physical_cleanup() -> None:
    session, version = _records(
        DocumentState.DELETING,
        index_state=DocumentIndexState.ACTIVE,
        legal_hold=True,
    )
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    worker = _worker(
        metadata,
        MemoryObjects(order),
        RecordingArtifacts(order),
        RecordingIndex(order),
        verifier=ReceiptVerifier(order),
    )
    claim = _claim(session.upload_id).model_copy(update={"stage": DocumentWorkerStage.DELETION})

    with pytest.raises(PurgeVerificationError, match="legal hold"):
        await worker.apply_deletion_request(_request(session, version), lambda: claim)

    assert order == ["tombstone"]
    assert metadata.version.retention_state is DocumentRetentionState.PURGE_PENDING


async def test_missing_verifier_fails_closed_after_cleanup() -> None:
    session, version = _records(
        DocumentState.DELETING,
        index_state=DocumentIndexState.ACTIVE,
    )
    metadata = MemoryMetadata(session, version)
    order: list[str] = []
    worker = _worker(
        metadata,
        MemoryObjects(order),
        RecordingArtifacts(order),
        RecordingIndex(order),
    )
    claim = _claim(session.upload_id).model_copy(update={"stage": DocumentWorkerStage.DELETION})

    with pytest.raises(PurgeVerificationError, match="not configured"):
        await worker.apply_deletion_request(_request(session, version), lambda: claim)

    assert metadata.version.state is DocumentState.DELETING
    assert metadata.version.retention_state is DocumentRetentionState.PURGE_PENDING
    assert next(iter(metadata.effects.values())).status is WorkerEffectStatus.PENDING


def _request(session: UploadSession, version: DocumentVersion) -> DocumentDeletionRequest:
    return DocumentDeletionRequest(
        request_id=UUID(int=5),
        idempotency_key="delete:1",
        document_id=version.document_id,
        version_id=version.version_id,
        upload_id=session.upload_id,
        requested_by="operator",
        expected_upload_revision=session.revision,
        expected_version_revision=version.revision,
        requested_at=NOW,
    )
