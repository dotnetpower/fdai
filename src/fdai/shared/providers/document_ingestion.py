"""Async provider seams for the document-ingestion plane."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    DocumentVersion,
    MalwareVerdict,
    ProtectionState,
    StructuralUnit,
    UploadSession,
)
from fdai.shared.providers.knowledge import KnowledgeChunk


class DocumentIngestionError(RuntimeError):
    """Base error safe for translation at the HTTP boundary."""


class DocumentNotFoundError(DocumentIngestionError):
    """Requested upload or version does not exist."""


class DocumentAccessDeniedError(DocumentIngestionError):
    """The principal is not permitted to perform the operation."""


@dataclass(frozen=True, slots=True)
class ChatDocumentRef:
    """Immutable governed document version selected by a conversation turn."""

    document_id: UUID
    version_id: UUID


class ProviderUnavailableError(DocumentIngestionError):
    """A mandatory safety provider cannot currently decide."""


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


@runtime_checkable
class DocumentAccessProvider(Protocol):
    async def authorize_create(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        collection_id: str,
    ) -> None: ...

    async def authorize_read(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None: ...

    async def authorize_delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None: ...


@runtime_checkable
class DocumentMetadataStore(Protocol):
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
class DocumentObjectStore(Protocol):
    async def issue_upload(self, session: UploadSession) -> UploadGrant: ...

    async def resume_upload(self, session: UploadSession) -> UploadGrant: ...

    async def stat(self, object_key: str) -> StoredObjectInfo: ...

    def read(self, object_key: str) -> AsyncIterator[bytes]: ...

    async def revoke_upload(self, upload_id: UUID) -> None: ...

    async def delete(self, object_key: str) -> None: ...


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
class PromotableDocumentObjectStore(Protocol):
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
    """Extract bounded, cited text units from one image or scanned PDF source."""

    async def extract(
        self,
        *,
        version: DocumentVersion,
        content: bytes,
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
class DocumentActivitySink(Protocol):
    async def audit(self, record: Mapping[str, object]) -> None: ...

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None: ...


__all__ = [
    "ChatDocumentRef",
    "DirectUploadStore",
    "DocumentAccessDeniedError",
    "DocumentAccessProvider",
    "DocumentActivitySink",
    "DocumentArtifactStore",
    "DocumentExtractor",
    "DocumentIndex",
    "DocumentIngestionError",
    "DocumentMetadataStore",
    "DocumentNotFoundError",
    "DocumentObjectStore",
    "DocumentReadyConsumer",
    "DocumentSearch",
    "ImageOcrProvider",
    "MalwareScanner",
    "ProtectionInspection",
    "ProtectionInspector",
    "PromotableDocumentObjectStore",
    "ProviderUnavailableError",
    "StoredObjectInfo",
    "StreamingUploadStore",
    "UploadGrant",
]
