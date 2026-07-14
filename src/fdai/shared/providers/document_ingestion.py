"""Async provider seams for the document-ingestion plane."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentVersion,
    MalwareVerdict,
    ProtectionState,
    UploadSession,
)


class DocumentIngestionError(RuntimeError):
    """Base error safe for translation at the HTTP boundary."""


class DocumentNotFoundError(DocumentIngestionError):
    """Requested upload or version does not exist."""


class DocumentAccessDeniedError(DocumentIngestionError):
    """The principal is not permitted to perform the operation."""


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
    async def authorize_create(self, *, actor_id: str, collection_id: str) -> None: ...

    async def authorize_read(self, *, actor_id: str, version: DocumentVersion) -> None: ...

    async def authorize_delete(self, *, actor_id: str, version: DocumentVersion) -> None: ...


@runtime_checkable
class DocumentMetadataStore(Protocol):
    async def create(self, session: UploadSession, version: DocumentVersion) -> None: ...

    async def get_upload(self, upload_id: UUID) -> UploadSession: ...

    async def save_upload(self, session: UploadSession) -> None: ...

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion: ...

    async def save_version(self, version: DocumentVersion) -> None: ...

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]: ...


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
class DocumentArtifactStore(Protocol):
    async def put(self, envelope: DocumentEnvelope) -> str: ...

    async def delete(self, document_id: UUID, version_id: UUID) -> None: ...


@runtime_checkable
class DocumentIndex(Protocol):
    async def commit(self, envelope: DocumentEnvelope) -> int: ...

    async def delete(self, document_id: UUID, version_id: UUID) -> None: ...


@runtime_checkable
class DocumentActivitySink(Protocol):
    async def audit(self, record: Mapping[str, object]) -> None: ...

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None: ...


__all__ = [
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
    "MalwareScanner",
    "ProtectionInspection",
    "ProtectionInspector",
    "ProviderUnavailableError",
    "StoredObjectInfo",
    "UploadGrant",
]
