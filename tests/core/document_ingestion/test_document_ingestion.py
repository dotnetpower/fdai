"""Document-ingestion contract, service, worker, and local adapter tests."""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from fdai.core.document_ingestion import (
    CreateUploadRequest,
    DocumentIngestionService,
    DocumentIngestionWorker,
    InvalidDocumentTransitionError,
    transition,
)
from fdai.shared.contracts import (
    DocumentPurpose,
    DocumentState,
    IngestionCapabilities,
    MalwareVerdict,
    ProtectionState,
    SourceStorageMode,
)
from fdai.shared.providers.document_ingestion import (
    DirectUploadStore,
    DocumentAccessProvider,
    DocumentActivitySink,
    DocumentArtifactStore,
    DocumentIndex,
    DocumentMetadataStore,
    DocumentObjectStore,
    MalwareScanner,
)
from fdai.shared.providers.local.document_ingestion import (
    LocalDirectoryDocumentObjectStore,
    SignatureProtectionInspector,
    StandardLibraryDocumentExtractor,
    UnavailableMalwareScanner,
)
from fdai.shared.providers.testing.document_ingestion import (
    InMemoryDocumentAccessProvider,
    InMemoryDocumentArtifactStore,
    InMemoryDocumentIndex,
    InMemoryDocumentMetadataStore,
    InMemoryDocumentObjectStore,
    RecordingDocumentActivitySink,
    StaticMalwareScanner,
)

_NOW = datetime(2026, 7, 14, tzinfo=UTC)


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> UUID:
        self.value += 1
        return UUID(int=self.value)


class _PromotableInMemoryStore(InMemoryDocumentObjectStore):
    def __init__(self, *, fail_once: bool = False) -> None:
        super().__init__(chunk_size=7)
        self.promoted: list[UUID] = []
        self.fail_once = fail_once

    async def promote(self, session) -> str:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("transient promotion failure")
        self.promoted.append(session.upload_id)
        return self.governed_key(session)

    def governed_key(self, session) -> str:
        return f"governed/{session.document_id.hex}/{session.version_id.hex}/source"


class _HangingArtifactStore:
    def __init__(self) -> None:
        self.deleted: list[tuple[UUID, UUID]] = []

    async def put(self, _envelope) -> str:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        self.deleted.append((document_id, version_id))


def _capabilities(*, direct_upload: bool = True) -> IngestionCapabilities:
    return IngestionCapabilities(
        supported_formats=("text", "ooxml", "pdf-detect-only"),
        storage_modes=tuple(SourceStorageMode),
        max_file_size=1024 * 1024,
        max_batch_count=10,
        archives_enabled=False,
        policy_versions=("policy-v1",),
        direct_upload=direct_upload,
    )


def _request(
    content: bytes,
    *,
    name: str = "guide.txt",
    document_id: UUID | None = None,
    supersedes_version_id: UUID | None = None,
):
    return CreateUploadRequest(
        source_name=name,
        collection_id="collection-a",
        media_type_hint="text/plain",
        expected_size=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        access_descriptor_ref="acl-1",
        reader_groups=("group-readers",),
        retention_policy_version="policy-v1",
        document_id=document_id,
        supersedes_version_id=supersedes_version_id,
    )


def _dependencies(
    *,
    malware: MalwareVerdict = MalwareVerdict.CLEAN,
    objects: InMemoryDocumentObjectStore | None = None,
    artifacts: DocumentArtifactStore | None = None,
    indexing_stage_timeout_seconds: float = 90.0,
):
    access = InMemoryDocumentAccessProvider(
        contributors={"collection-a": frozenset({"uploader"})},
        readers={"collection-a": frozenset({"reader"})},
        owners={"collection-a": frozenset({"owner"})},
    )
    metadata = InMemoryDocumentMetadataStore()
    objects = objects or InMemoryDocumentObjectStore(chunk_size=7)
    artifacts = artifacts or InMemoryDocumentArtifactStore()
    index = InMemoryDocumentIndex()
    activity = RecordingDocumentActivitySink()
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=objects,
        activity=activity,
        capabilities=_capabilities(),
        clock=lambda: _NOW,
        id_factory=_Ids(),
    )
    worker = DocumentIngestionWorker(
        access=access,
        metadata=metadata,
        objects=objects,
        malware=StaticMalwareScanner(malware),
        protection=SignatureProtectionInspector(),
        extractor=StandardLibraryDocumentExtractor(),
        artifacts=artifacts,
        index=index,
        activity=activity,
        clock=lambda: _NOW,
        indexing_stage_timeout_seconds=indexing_stage_timeout_seconds,
    )
    return service, worker, metadata, objects, artifacts, index, activity


async def test_managed_copy_promotes_source_before_ready() -> None:
    objects = _PromotableInMemoryStore()
    service, worker, metadata, _, _, _, _ = _dependencies(objects=objects)
    session = await _upload(service, b"managed content")

    version = await worker.process(session.upload_id)
    persisted = await metadata.get_upload(session.upload_id)

    assert version.state is DocumentState.READY
    assert objects.promoted == [session.upload_id]
    assert persisted.object_key.startswith("governed/")


async def test_worker_resumes_indexing_and_terminal_redelivery_is_noop() -> None:
    service, worker, metadata, _, _, _, activity = _dependencies()
    session = await _upload(service, b"resume content")
    version = await metadata.get_version(session.document_id, session.version_id)
    interrupted_session = session.model_copy(update={"state": DocumentState.INDEXING})
    interrupted_version = version.model_copy(
        update={
            "state": DocumentState.INDEXING,
            "observed_format": "text",
            "protection_state": ProtectionState.NONE,
        }
    )
    await metadata.save_upload(interrupted_session)
    await metadata.save_version(interrupted_version)

    ready = await worker.process(session.upload_id)
    audit_count = len(activity.audit_records)
    replayed = await worker.process(session.upload_id)

    assert ready.state is DocumentState.READY
    assert replayed == ready
    assert len(activity.audit_records) == audit_count


async def test_transient_promotion_failure_restores_source_path_for_retry() -> None:
    objects = _PromotableInMemoryStore(fail_once=True)
    service, worker, metadata, _, _, _, _ = _dependencies(objects=objects)
    session = await _upload(service, b"retry promotion")

    with pytest.raises(RuntimeError, match="transient promotion"):
        await worker.process(session.upload_id)

    interrupted = await metadata.get_upload(session.upload_id)
    assert interrupted.state is DocumentState.INDEXING
    assert interrupted.object_key == session.object_key

    ready = await worker.process(session.upload_id)
    assert ready.state is DocumentState.READY
    assert (await metadata.get_upload(session.upload_id)).object_key.startswith("governed/")


async def _upload(
    service,
    content: bytes,
    *,
    name: str = "guide.txt",
    document_id=None,
    supersedes_version_id=None,
):
    session, _ = await service.create_upload(
        actor_id="uploader",
        request=_request(
            content,
            name=name,
            document_id=document_id,
            supersedes_version_id=supersedes_version_id,
        ),
    )
    await service.put_local_content(
        actor_id="uploader", upload_id=session.upload_id, content=content
    )
    await service.complete_upload(actor_id="uploader", upload_id=session.upload_id)
    return session


def test_contracts_are_frozen_and_reject_unknown_fields() -> None:
    capabilities = _capabilities()
    with pytest.raises(ValidationError):
        capabilities.max_file_size = 1
    with pytest.raises(ValidationError):
        IngestionCapabilities(**capabilities.model_dump(), unknown=True)


def test_handover_bootstrap_is_a_supported_document_purpose() -> None:
    request = _request(b"RACI: Jordan is accountable for monitoring")
    parsed = replace(
        request,
        purposes=(DocumentPurpose("handover_bootstrap"),),
    )

    assert parsed.purposes == (DocumentPurpose.HANDOVER_BOOTSTRAP,)


def test_state_machine_rejects_skipped_safety_stage() -> None:
    assert (
        transition(DocumentState.RECEIVED, DocumentState.QUARANTINED) is DocumentState.QUARANTINED
    )
    with pytest.raises(InvalidDocumentTransitionError):
        transition(DocumentState.RECEIVED, DocumentState.READY)


def test_in_memory_adapters_satisfy_runtime_provider_contracts() -> None:
    _, _, metadata, objects, artifacts, index, activity = _dependencies()
    access = InMemoryDocumentAccessProvider()
    malware = StaticMalwareScanner()
    assert isinstance(access, DocumentAccessProvider)
    assert isinstance(metadata, DocumentMetadataStore)
    assert isinstance(objects, DocumentObjectStore)
    assert isinstance(objects, DirectUploadStore)
    assert isinstance(malware, MalwareScanner)
    assert isinstance(artifacts, DocumentArtifactStore)
    assert isinstance(index, DocumentIndex)
    assert isinstance(activity, DocumentActivitySink)


async def test_local_object_store_round_trip_and_traversal_defense(tmp_path) -> None:
    service, _, _, _, _, _, _ = _dependencies()
    session, _ = await service.create_upload(actor_id="uploader", request=_request(b"local"))
    local = LocalDirectoryDocumentObjectStore(tmp_path)
    await local.put(session.object_key, b"local")
    chunks = [chunk async for chunk in local.read(session.object_key)]
    assert b"".join(chunks) == b"local"
    assert (await local.stat(session.object_key)).sha256 == hashlib.sha256(b"local").hexdigest()
    with pytest.raises(ValueError, match="escapes"):
        await local.put("../escape", b"blocked")


async def test_service_verifies_object_and_emits_metadata_only_activity() -> None:
    service, _, _, _, _, _, activity = _dependencies()
    content = b"safe text\nsecond line"
    session = await _upload(service, content)

    status = await service.get_upload(actor_id="reader", upload_id=session.upload_id)
    assert status.state is DocumentState.RECEIVED
    assert activity.events[-1][0] == "document.received"
    serialized = repr(activity.audit_records)
    assert "safe text" not in serialized
    assert "guide.txt" not in serialized


async def test_storage_commit_mismatch_holds_source() -> None:
    service, _, metadata, _, _, _, _ = _dependencies()
    declared = b"declared"
    session, _ = await service.create_upload(actor_id="uploader", request=_request(declared))
    await service.put_local_content(
        actor_id="uploader", upload_id=session.upload_id, content=b"tampered"
    )
    with pytest.raises(ValueError, match="does not match"):
        await service.complete_upload(actor_id="uploader", upload_id=session.upload_id)
    version = await metadata.get_version(session.document_id, session.version_id)
    assert version.state is DocumentState.HELD
    assert version.failure_code == "storage_commit_mismatch"


async def test_safe_text_reaches_ready_and_indexes_line_citations() -> None:
    service, worker, _, _, artifacts, index, activity = _dependencies()
    session = await _upload(service, b"first\nsecond\n")
    version = await worker.process(session.upload_id)

    assert version.state is DocumentState.READY
    assert version.available and version.active
    envelope = artifacts.envelopes[(session.document_id, session.version_id)]
    assert [unit.locator for unit in envelope.units] == ["line:1", "line:2"]
    assert (session.document_id, session.version_id) in index.envelopes
    assert activity.events[-1][0] == "document.ready"


async def test_hung_artifact_write_times_out_and_fails_closed() -> None:
    artifacts = _HangingArtifactStore()
    service, worker, _, _, _, index, _ = _dependencies(
        artifacts=artifacts,
        indexing_stage_timeout_seconds=0.01,
    )
    session = await _upload(service, b"content")

    version = await worker.process(session.upload_id)

    assert version.state is DocumentState.FAILED
    assert version.failure_code == "indexing_failed"
    assert not index.envelopes
    assert artifacts.deleted == [(session.document_id, session.version_id)]


@pytest.mark.parametrize(
    ("scanner", "failure_code"),
    [
        (MalwareVerdict.INFECTED, "malware_detected"),
        (MalwareVerdict.UNAVAILABLE, "malware_scanner_unavailable"),
    ],
)
async def test_malware_non_clean_verdict_holds(scanner, failure_code) -> None:
    service, worker, _, _, artifacts, index, _ = _dependencies(malware=scanner)
    session = await _upload(service, b"content")
    version = await worker.process(session.upload_id)
    assert version.state is DocumentState.HELD
    assert version.failure_code == failure_code
    assert not artifacts.envelopes and not index.envelopes


async def test_unavailable_default_scanner_abstains() -> None:
    async def chunks():
        yield b"content"

    assert await UnavailableMalwareScanner().scan(chunks()) is MalwareVerdict.UNAVAILABLE


@pytest.mark.parametrize(
    ("content", "name", "expected"),
    [
        (b"%PDF-1.7\n1 0 obj << /Encrypt 2 0 R >>", "file.pdf", ProtectionState.PASSWORD_ENCRYPTED),
        (
            bytes.fromhex("d0cf11e0a1b11ae1") + b"data",
            "file.docx",
            ProtectionState.PASSWORD_ENCRYPTED,
        ),
        (b"\x00\x01\x02binary", "file.bin", ProtectionState.UNKNOWN),
    ],
)
async def test_signature_protection_detection(content, name, expected) -> None:
    async def chunks():
        yield content

    result = await SignatureProtectionInspector().inspect(
        source_name=name,
        media_type_hint="application/octet-stream",
        chunks=chunks(),
    )
    assert result.state is expected


async def test_encrypted_pdf_is_held_before_extraction() -> None:
    service, worker, _, _, artifacts, index, _ = _dependencies()
    content = b"%PDF-1.7\n1 0 obj << /Encrypt 2 0 R >>"
    session = await _upload(service, content, name="protected.pdf")
    version = await worker.process(session.upload_id)
    assert version.state is DocumentState.HELD
    assert version.protection_state is ProtectionState.PASSWORD_ENCRYPTED
    assert not artifacts.envelopes and not index.envelopes


async def test_safe_docx_extracts_text_without_executing_content() -> None:
    content = _docx(b"<w:document xmlns:w='urn:w'><w:body><w:t>Hello</w:t></w:body></w:document>")
    service, worker, _, _, artifacts, _, _ = _dependencies()
    session = await _upload(service, content, name="guide.docx")
    version = await worker.process(session.upload_id)
    envelope = artifacts.envelopes[(session.document_id, session.version_id)]
    assert version.state is DocumentState.READY
    assert envelope.units[0].text == "Hello"
    assert envelope.units[0].locator == "word/document.xml"


async def test_replacement_moves_active_pointer_only_after_ready() -> None:
    service, worker, metadata, _, _, _, _ = _dependencies()
    first = await _upload(service, b"v1")
    first_ready = await worker.process(first.upload_id)
    second = await _upload(
        service,
        b"v2",
        document_id=first.document_id,
        supersedes_version_id=first.version_id,
    )

    before = await metadata.get_version(first.document_id, first.version_id)
    assert before.active
    await worker.process(second.upload_id)
    after = await metadata.get_version(first.document_id, first.version_id)
    latest = await metadata.get_version(second.document_id, second.version_id)
    assert first_ready.active and not after.active and latest.active


async def test_delete_removes_source_artifact_and_index_before_tombstone() -> None:
    service, worker, metadata, objects, artifacts, index, activity = _dependencies()
    session = await _upload(service, b"delete me")
    await worker.process(session.upload_id)
    deleted = await worker.delete(
        actor_id="uploader",
        document_id=session.document_id,
        version_id=session.version_id,
    )
    assert deleted.state is DocumentState.DELETED
    assert not deleted.available
    assert session.object_key not in objects.objects
    assert not artifacts.envelopes and not index.envelopes
    assert activity.events[-1][0] == "document.deleted"
    persisted = await metadata.get_version(session.document_id, session.version_id)
    assert persisted.state is DocumentState.DELETED


def _docx(document_xml: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()
