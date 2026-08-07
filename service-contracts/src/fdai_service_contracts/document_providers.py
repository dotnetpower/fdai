"""Provider Protocols shared by independent document services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai_service_contracts.document import (
    DocumentEnvelope,
    DocumentPurpose,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerStage,
    EventEnvelope,
    ExtractionUnavailableReason,
    MalwareVerdict,
    ProtectionState,
    StructuralUnit,
    UploadSession,
)
from fdai_service_contracts.handover import (
    HandoverDraftArtifact,
    RepositoryHandoverDraft,
    ResolvedStewardIdentity,
    StewardshipMergeRecord,
)


class DocumentIngestionError(RuntimeError):
    """Base error safe for translation at an HTTP boundary."""


class DocumentNotFoundError(DocumentIngestionError):
    """Requested upload or version does not exist."""


class DocumentAccessDeniedError(DocumentIngestionError):
    """The principal is not permitted to perform the operation."""


class DocumentWorkerClaimConflictError(DocumentIngestionError):
    """A worker claim changed owner, attempt, revision, or lease state."""


class ProviderUnavailableError(DocumentIngestionError):
    """A mandatory provider cannot currently decide."""


class DocumentExtractionUnavailableError(ValueError):
    """Sanitized bounded-parser outcome safe to persist as a failure code."""

    def __init__(self, reason: ExtractionUnavailableReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True, slots=True)
class UploadGrant:
    upload_id: UUID
    target: str
    expires_at: datetime
    completed_parts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredObjectInfo:
    object_key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ProtectionInspection:
    state: ProtectionState
    observed_format: str
    media_type: str
    sensitivity_label: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    doc_id: str
    chunk_id: str
    text: str
    source_ref: str
    metadata: Mapping[str, object]
    score: float = 0.0


@runtime_checkable
class DocumentAccessProvider(Protocol):
    async def authorize_create(
        self, *, actor_id: str, actor_groups: frozenset[str], collection_id: str
    ) -> None: ...

    async def authorize_read(
        self, *, actor_id: str, actor_groups: frozenset[str], version: DocumentVersion
    ) -> None: ...

    async def authorize_delete(
        self, *, actor_id: str, actor_groups: frozenset[str], version: DocumentVersion
    ) -> None: ...


@runtime_checkable
class DocumentUploadMetadataStore(Protocol):
    """Upload and version records written by the API and processing pipeline."""

    async def create(self, session: UploadSession, version: DocumentVersion) -> None: ...
    async def get_upload(self, upload_id: UUID) -> UploadSession: ...
    async def save_upload(self, session: UploadSession) -> None: ...
    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion: ...
    async def save_version(self, version: DocumentVersion) -> None: ...
    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]: ...
    async def list_uploads_by_state(
        self, state: str, *, limit: int
    ) -> tuple[UploadSession, ...]: ...


@runtime_checkable
class DocumentMetadataStore(DocumentUploadMetadataStore, Protocol):
    """Worker extension that owns durable stage-claim transitions."""

    async def claim_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        lease_seconds: int,
    ) -> DocumentWorkerClaim | None: ...
    async def complete_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim: ...
    async def renew_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        lease_seconds: int,
    ) -> DocumentWorkerClaim: ...
    async def release_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim: ...


@runtime_checkable
class WorkerDocumentObjectStore(Protocol):
    """Worker source access without upload-grant authority."""

    def read(self, object_key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, object_key: str) -> None: ...


@runtime_checkable
class DocumentObjectStore(WorkerDocumentObjectStore, Protocol):
    """API upload-grant and source metadata operations."""

    async def issue_upload(self, session: UploadSession) -> UploadGrant: ...
    async def resume_upload(self, session: UploadSession) -> UploadGrant: ...
    async def stat(self, object_key: str) -> StoredObjectInfo: ...
    async def revoke_upload(self, upload_id: UUID) -> None: ...


@runtime_checkable
class DirectUploadStore(Protocol):
    async def put(self, object_key: str, content: bytes) -> StoredObjectInfo: ...


@runtime_checkable
class StreamingUploadStore(Protocol):
    async def put_stream(
        self,
        object_key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> StoredObjectInfo: ...


@runtime_checkable
class PromotableDocumentObjectStore(WorkerDocumentObjectStore, Protocol):
    def governed_key(self, session: UploadSession) -> str: ...
    async def promote(self, session: UploadSession) -> str: ...


@runtime_checkable
class MalwareScanner(Protocol):
    async def scan(self, chunks: AsyncIterator[bytes]) -> MalwareVerdict: ...


@runtime_checkable
class ProtectionInspector(Protocol):
    async def inspect(
        self, *, source_name: str, media_type_hint: str, chunks: AsyncIterator[bytes]
    ) -> ProtectionInspection: ...


@runtime_checkable
class DocumentExtractor(Protocol):
    async def extract(
        self, *, version: DocumentVersion, chunks: AsyncIterator[bytes]
    ) -> DocumentEnvelope: ...


@runtime_checkable
class ImageOcrProvider(Protocol):
    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]: ...


@runtime_checkable
class DocumentArtifactStore(Protocol):
    async def put(self, envelope: DocumentEnvelope) -> str: ...
    async def delete(self, document_id: UUID, version_id: UUID) -> None: ...


@runtime_checkable
class DocumentIndex(Protocol):
    async def commit(self, envelope: DocumentEnvelope) -> int: ...
    async def delete(self, document_id: UUID, version_id: UUID) -> None: ...


@runtime_checkable
class DocumentSearch(Protocol):
    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> Sequence[KnowledgeChunk]: ...


@runtime_checkable
class DocumentReadyConsumer(Protocol):
    @property
    def purpose(self) -> DocumentPurpose: ...

    async def consume(
        self, *, session: UploadSession, envelope: DocumentEnvelope
    ) -> tuple[str, ...]: ...


@runtime_checkable
class StewardPersonDirectory(Protocol):
    """Resolve one exact display name, returning None for unknown or ambiguous names."""

    async def resolve(self, display_name: str) -> ResolvedStewardIdentity | None: ...


@runtime_checkable
class HandoverDraftStore(Protocol):
    """Persist review-only drafts produced by the document worker."""

    async def put(self, artifact: HandoverDraftArtifact) -> None: ...


@runtime_checkable
class StewardshipMergeRecorder(Protocol):
    """Record one verified merge exactly once by delivery id."""

    async def record(self, merge: StewardshipMergeRecord) -> bool: ...


@runtime_checkable
class RepositoryHandoverDraftRecorder(Protocol):
    """Persist one authenticated inert repository draft by delivery id."""

    async def record(self, draft: RepositoryHandoverDraft) -> bool: ...


@runtime_checkable
class DocumentActivitySink(Protocol):
    async def audit(self, record: Mapping[str, object]) -> None: ...
    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None: ...


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None: ...
    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]: ...
    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
        reason: str,
    ) -> None: ...
    async def close(self) -> None: ...
