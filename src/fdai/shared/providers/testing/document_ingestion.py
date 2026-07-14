"""Deterministic in-memory document-ingestion adapters for tests and dev."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from uuid import UUID

from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentVersion,
    MalwareVerdict,
    UploadSession,
)
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    StoredObjectInfo,
    UploadGrant,
)


class InMemoryDocumentAccessProvider:
    def __init__(
        self,
        *,
        contributors: Mapping[str, frozenset[str]] | None = None,
        readers: Mapping[str, frozenset[str]] | None = None,
        owners: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self._contributors = dict(contributors or {})
        self._readers = dict(readers or {})
        self._owners = dict(owners or {})

    async def authorize_create(self, *, actor_id: str, collection_id: str) -> None:
        allowed = self._contributors.get(collection_id, frozenset()) | self._owners.get(
            collection_id, frozenset()
        )
        if actor_id not in allowed:
            raise DocumentAccessDeniedError("collection contributor access is required")

    async def authorize_read(self, *, actor_id: str, version: DocumentVersion) -> None:
        allowed = (
            self._readers.get(version.access.collection_id, frozenset())
            | self._contributors.get(version.access.collection_id, frozenset())
            | self._owners.get(version.access.collection_id, frozenset())
            | frozenset({version.uploader_id})
        )
        if actor_id not in allowed:
            raise DocumentAccessDeniedError("document metadata access is denied")

    async def authorize_delete(self, *, actor_id: str, version: DocumentVersion) -> None:
        allowed = self._owners.get(version.access.collection_id, frozenset()) | frozenset(
            {version.uploader_id}
        )
        if actor_id not in allowed:
            raise DocumentAccessDeniedError("document delete access is denied")


class InMemoryDocumentMetadataStore:
    def __init__(self) -> None:
        self.uploads: dict[UUID, UploadSession] = {}
        self.versions: dict[tuple[UUID, UUID], DocumentVersion] = {}

    async def create(self, session: UploadSession, version: DocumentVersion) -> None:
        if session.upload_id in self.uploads:
            raise ValueError("upload id already exists")
        self.uploads[session.upload_id] = session
        self.versions[(version.document_id, version.version_id)] = version

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        try:
            return self.uploads[upload_id]
        except KeyError as exc:
            raise DocumentNotFoundError("upload was not found") from exc

    async def save_upload(self, session: UploadSession) -> None:
        if session.upload_id not in self.uploads:
            raise DocumentNotFoundError("upload was not found")
        self.uploads[session.upload_id] = session

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        try:
            return self.versions[(document_id, version_id)]
        except KeyError as exc:
            raise DocumentNotFoundError("document version was not found") from exc

    async def save_version(self, version: DocumentVersion) -> None:
        key = (version.document_id, version.version_id)
        if key not in self.versions:
            raise DocumentNotFoundError("document version was not found")
        if version.active:
            for current_key, current in tuple(self.versions.items()):
                if current.document_id == version.document_id and current_key != key:
                    self.versions[current_key] = current.model_copy(update={"active": False})
        self.versions[key] = version

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        versions = [v for v in self.versions.values() if v.document_id == document_id]
        if not versions:
            raise DocumentNotFoundError("document was not found")
        return tuple(sorted(versions, key=lambda item: item.created_at))


class InMemoryDocumentObjectStore:
    def __init__(self, *, chunk_size: int = 64 * 1024) -> None:
        self.objects: dict[str, bytes] = {}
        self.revoked: set[UUID] = set()
        self._chunk_size = chunk_size

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(session.upload_id, f"memory://{session.object_key}", session.expires_at)

    async def resume_upload(self, session: UploadSession) -> UploadGrant:
        if session.upload_id in self.revoked:
            raise ValueError("upload grant has been revoked")
        return await self.issue_upload(session)

    async def put(self, object_key: str, content: bytes) -> StoredObjectInfo:
        self.objects[object_key] = bytes(content)
        return _object_info(object_key, content)

    async def stat(self, object_key: str) -> StoredObjectInfo:
        try:
            content = self.objects[object_key]
        except KeyError as exc:
            raise DocumentNotFoundError("source object was not found") from exc
        return _object_info(object_key, content)

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        try:
            content = self.objects[object_key]
        except KeyError as exc:
            raise DocumentNotFoundError("source object was not found") from exc
        for offset in range(0, len(content), self._chunk_size):
            yield content[offset : offset + self._chunk_size]

    async def revoke_upload(self, upload_id: UUID) -> None:
        self.revoked.add(upload_id)

    async def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


@dataclass
class StaticMalwareScanner:
    verdict: MalwareVerdict = MalwareVerdict.CLEAN

    async def scan(self, chunks: AsyncIterator[bytes]) -> MalwareVerdict:
        async for _ in chunks:
            pass
        return self.verdict


class InMemoryDocumentArtifactStore:
    def __init__(self) -> None:
        self.envelopes: dict[tuple[UUID, UUID], DocumentEnvelope] = {}

    async def put(self, envelope: DocumentEnvelope) -> str:
        self.envelopes[(envelope.document_id, envelope.version_id)] = envelope
        return f"artifact://{envelope.document_id}/{envelope.version_id}"

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        self.envelopes.pop((document_id, version_id), None)


class InMemoryDocumentIndex:
    def __init__(self) -> None:
        self.envelopes: dict[tuple[UUID, UUID], DocumentEnvelope] = {}

    async def commit(self, envelope: DocumentEnvelope) -> int:
        self.envelopes[(envelope.document_id, envelope.version_id)] = envelope
        return len(envelope.units)

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        self.envelopes.pop((document_id, version_id), None)


class RecordingDocumentActivitySink:
    def __init__(self) -> None:
        self.audit_records: list[dict[str, object]] = []
        self.events: list[tuple[str, str, dict[str, object]]] = []

    async def audit(self, record: Mapping[str, object]) -> None:
        self.audit_records.append(dict(record))

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        self.events.append((topic, key, dict(payload)))


def _object_info(object_key: str, content: bytes) -> StoredObjectInfo:
    return StoredObjectInfo(
        object_key=object_key,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


__all__ = [
    "InMemoryDocumentAccessProvider",
    "InMemoryDocumentArtifactStore",
    "InMemoryDocumentIndex",
    "InMemoryDocumentMetadataStore",
    "InMemoryDocumentObjectStore",
    "RecordingDocumentActivitySink",
    "StaticMalwareScanner",
]
