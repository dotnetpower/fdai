"""Deterministic in-memory document-ingestion adapters for tests and dev."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    MalwareVerdict,
    UploadSession,
)
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    DocumentWorkerClaimConflictError,
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

    async def authorize_create(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str] = frozenset(),
        collection_id: str,
    ) -> None:
        allowed = self._contributors.get(collection_id, frozenset()) | self._owners.get(
            collection_id, frozenset()
        )
        if actor_id not in allowed and not actor_groups.intersection(allowed):
            raise DocumentAccessDeniedError("collection contributor access is required")

    async def authorize_read(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str] = frozenset(),
        version: DocumentVersion,
    ) -> None:
        allowed = (
            self._readers.get(version.access.collection_id, frozenset())
            | self._contributors.get(version.access.collection_id, frozenset())
            | self._owners.get(version.access.collection_id, frozenset())
            | frozenset({version.uploader_id})
        )
        if actor_id not in allowed and not actor_groups.intersection(allowed):
            raise DocumentAccessDeniedError("document metadata access is denied")

    async def authorize_delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str] = frozenset(),
        version: DocumentVersion,
    ) -> None:
        allowed = self._owners.get(version.access.collection_id, frozenset()) | frozenset(
            {version.uploader_id}
        )
        if actor_id not in allowed and not actor_groups.intersection(allowed):
            raise DocumentAccessDeniedError("document delete access is denied")


class InMemoryDocumentMetadataStore:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.uploads: dict[UUID, UploadSession] = {}
        self.versions: dict[tuple[UUID, UUID], DocumentVersion] = {}
        self.worker_claims: dict[tuple[UUID, DocumentWorkerStage], DocumentWorkerClaim] = {}
        self._clock = clock or (lambda: datetime.now(UTC))
        self._worker_claim_lock = asyncio.Lock()

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

    async def list_uploads_by_state(self, state: str, *, limit: int) -> tuple[UploadSession, ...]:
        uploads = [upload for upload in self.uploads.values() if upload.state.value == state]
        return tuple(sorted(uploads, key=lambda item: item.created_at)[:limit])

    async def claim_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        lease_seconds: int,
    ) -> DocumentWorkerClaim | None:
        if not owner or lease_seconds < 1:
            raise ValueError("document worker owner and lease MUST be valid")
        now = self._clock()
        key = (upload_id, stage)
        async with self._worker_claim_lock:
            current = self.worker_claims.get(key)
            if current is not None:
                if current.status is DocumentWorkerClaimStatus.COMPLETED:
                    return None
                if current.status is DocumentWorkerClaimStatus.ACTIVE:
                    if (
                        current.owner == owner
                        and current.attempt_id == attempt_id
                        and current.lease_expires_at > now
                    ):
                        return current
                    if current.lease_expires_at > now:
                        return None
                    if current.attempt_id == attempt_id:
                        return None
                if (
                    current.status is DocumentWorkerClaimStatus.RELEASED
                    and current.attempt_id == attempt_id
                ):
                    return None
            claim = DocumentWorkerClaim(
                upload_id=upload_id,
                stage=stage,
                owner=owner,
                attempt_id=attempt_id,
                revision=1 if current is None else current.revision + 1,
                status=DocumentWorkerClaimStatus.ACTIVE,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            self.worker_claims[key] = claim
            return claim

    async def complete_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim:
        return await self._finish_worker_stage(
            upload_id,
            stage,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            status=DocumentWorkerClaimStatus.COMPLETED,
        )

    async def renew_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        lease_seconds: int,
    ) -> DocumentWorkerClaim:
        if lease_seconds < 1:
            raise ValueError("document worker lease MUST be positive")
        now = self._clock()
        key = (upload_id, stage)
        async with self._worker_claim_lock:
            current = self.worker_claims.get(key)
            if (
                current is None
                or current.status is not DocumentWorkerClaimStatus.ACTIVE
                or current.owner != owner
                or current.attempt_id != attempt_id
                or current.revision != expected_revision
                or current.lease_expires_at <= now
            ):
                raise DocumentWorkerClaimConflictError("document worker claim conflict")
            renewed = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                }
            )
            self.worker_claims[key] = renewed
            return renewed

    async def release_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim:
        return await self._finish_worker_stage(
            upload_id,
            stage,
            owner=owner,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            status=DocumentWorkerClaimStatus.RELEASED,
        )

    async def _finish_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
        status: DocumentWorkerClaimStatus,
    ) -> DocumentWorkerClaim:
        now = self._clock()
        key = (upload_id, stage)
        async with self._worker_claim_lock:
            current = self.worker_claims.get(key)
            if (
                current is not None
                and current.status is status
                and current.owner == owner
                and current.attempt_id == attempt_id
                and current.revision == expected_revision + 1
            ):
                return current
            if (
                current is None
                or current.status is not DocumentWorkerClaimStatus.ACTIVE
                or current.owner != owner
                or current.attempt_id != attempt_id
                or current.revision != expected_revision
                or current.lease_expires_at <= now
            ):
                raise DocumentWorkerClaimConflictError("document worker claim conflict")
            finished = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": status,
                    "finished_at": now,
                }
            )
            self.worker_claims[key] = finished
            return finished


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

    async def put_stream(
        self,
        object_key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> StoredObjectInfo:
        content = bytearray()
        async for chunk in chunks:
            content.extend(chunk)
            if len(content) > max_size:
                raise ValueError("content exceeds the advertised file-size limit")
        if len(content) != expected_size:
            raise ValueError("streamed content size does not match the upload session")
        return await self.put(object_key, bytes(content))

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
