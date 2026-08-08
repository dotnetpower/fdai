"""Upload lifecycle application service owned by the Document Ingestion API."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fdai_service_contracts import (
    AccessDescriptor,
    DirectUploadStore,
    DocumentAccessProvider,
    DocumentDeletionRequest,
    DocumentLifecycleEvent,
    DocumentObjectStore,
    DocumentPurpose,
    DocumentState,
    DocumentUploadMetadataStore,
    DocumentVersion,
    IngestionCapabilities,
    RetentionPolicy,
    SourceStorageMode,
    StreamingUploadStore,
    UploadGrant,
    UploadSession,
)

from fdai_ingestion_api_service.state_machine import transition

_COMPLETED_UPLOAD_STATES = frozenset(
    {
        DocumentState.RECEIVED,
        DocumentState.QUARANTINED,
        DocumentState.SCANNING,
        DocumentState.PROTECTION_CHECK,
        DocumentState.EXTRACTING,
        DocumentState.INDEXING,
        DocumentState.READY,
        DocumentState.READY_WITH_WARNINGS,
        DocumentState.HELD,
        DocumentState.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class CreateUploadRequest:
    """Validated application command for creating one upload session."""

    source_name: str
    collection_id: str
    media_type_hint: str
    expected_size: int
    expected_sha256: str
    storage_mode: SourceStorageMode
    purposes: tuple[DocumentPurpose, ...]
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    document_id: UUID | None = None
    supersedes_version_id: UUID | None = None


class DocumentIngestionService:
    """Coordinate API-owned upload transitions through injected I/O providers."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentUploadMetadataStore,
        objects: DocumentObjectStore,
        capabilities: IngestionCapabilities,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
        upload_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._capabilities = capabilities
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or uuid4
        self._upload_ttl = upload_ttl

    @property
    def capabilities(self) -> IngestionCapabilities:
        return self._capabilities

    async def create_upload(
        self,
        *,
        actor_id: str,
        request: CreateUploadRequest,
        actor_groups: frozenset[str] = frozenset(),
    ) -> tuple[UploadSession, UploadGrant]:
        await self._access.authorize_create(
            actor_id=actor_id,
            actor_groups=actor_groups,
            collection_id=request.collection_id,
        )
        if request.document_id is None and request.supersedes_version_id is not None:
            raise ValueError("supersedes_version_id requires document_id")
        if request.document_id is not None:
            if request.supersedes_version_id is None:
                raise ValueError("a replacement requires supersedes_version_id")
            previous = await self._metadata.get_version(
                request.document_id, request.supersedes_version_id
            )
            await self._access.authorize_delete(
                actor_id=actor_id,
                actor_groups=actor_groups,
                version=previous,
            )
            if previous.access.collection_id != request.collection_id:
                raise ValueError("a replacement cannot move a document between collections")
        if request.expected_size > self._capabilities.max_file_size:
            raise ValueError("expected_size exceeds the advertised file-size limit")
        if request.storage_mode not in self._capabilities.storage_modes:
            raise ValueError("requested storage mode is unavailable")
        if not request.purposes:
            raise ValueError("at least one document purpose is required")

        now = self._clock()
        upload_id = self._id_factory()
        document_id = request.document_id or self._id_factory()
        version_id = self._id_factory()
        access = AccessDescriptor(
            reference=request.access_descriptor_ref,
            collection_id=request.collection_id,
            reader_groups=request.reader_groups,
        )
        retention = RetentionPolicy(policy_version=request.retention_policy_version)
        session = UploadSession(
            upload_id=upload_id,
            document_id=document_id,
            version_id=version_id,
            actor_id=actor_id,
            source_name=request.source_name,
            collection_id=request.collection_id,
            object_key=f"quarantine/{_collection_segment(request.collection_id)}/{upload_id.hex}",
            media_type_hint=request.media_type_hint,
            expected_size=request.expected_size,
            expected_sha256=request.expected_sha256,
            state=DocumentState.CREATED,
            storage_mode=request.storage_mode,
            purposes=request.purposes,
            access=access,
            retention=retention,
            created_at=now,
            expires_at=now + self._upload_ttl,
            supersedes_version_id=request.supersedes_version_id,
        )
        version = DocumentVersion(
            document_id=document_id,
            version_id=version_id,
            upload_id=upload_id,
            source_name=request.source_name,
            source_sha256=request.expected_sha256,
            size_bytes=request.expected_size,
            media_type=request.media_type_hint,
            state=DocumentState.CREATED,
            access=access,
            retention=retention,
            purposes=request.purposes,
            uploader_id=actor_id,
            created_at=now,
            updated_at=now,
            supersedes_version_id=request.supersedes_version_id,
        )
        await self._metadata.create(session, version)
        grant = await self._objects.issue_upload(session)
        uploading = transition(DocumentState.CREATED, DocumentState.UPLOADING)
        uploading_session = session.model_copy(
            update={"state": uploading, "revision": session.revision + 1}
        )
        uploading_version = version.model_copy(
            update={
                "state": uploading,
                "updated_at": self._clock(),
                "revision": version.revision + 1,
            }
        )
        try:
            await self._commit_transition(
                session,
                version,
                uploading_session,
                uploading_version,
                actor_id=actor_id,
                action="upload.created",
            )
        except BaseException:
            await self._objects.revoke_upload(session.upload_id)
            raise
        return uploading_session, grant

    async def resume_upload(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> UploadGrant:
        session, version = await self._authorized_upload(upload_id)
        if session.state is not DocumentState.UPLOADING:
            raise ValueError("only an uploading session can be resumed")
        if session.expires_at <= self._clock():
            raise ValueError("upload session has expired")
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        return await self._objects.resume_upload(session)

    async def put_local_content(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        content: bytes,
        actor_groups: frozenset[str] = frozenset(),
    ) -> None:
        session, version = await self._authorized_upload(upload_id)
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if session.state is not DocumentState.UPLOADING:
            raise ValueError("upload session is not accepting content")
        if len(content) > self._capabilities.max_file_size:
            raise ValueError("content exceeds the advertised file-size limit")
        if not isinstance(self._objects, DirectUploadStore):
            raise RuntimeError("direct upload is not supported by the object store")
        await self._objects.put(session.object_key, content)

    async def put_streaming_content(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        chunks: AsyncIterator[bytes],
        actor_groups: frozenset[str] = frozenset(),
    ) -> None:
        session, version = await self._authorized_upload(upload_id)
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if session.state is not DocumentState.UPLOADING:
            raise ValueError("upload session is not accepting content")
        if not isinstance(self._objects, StreamingUploadStore):
            raise RuntimeError("streaming upload is not supported by the object store")
        await self._objects.put_stream(
            session.object_key,
            chunks,
            expected_size=session.expected_size,
            max_size=self._capabilities.max_file_size,
        )

    async def complete_upload(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> UploadSession:
        session, version = await self._authorized_upload(upload_id)
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if session.state is not DocumentState.UPLOADING:
            if session.state in _COMPLETED_UPLOAD_STATES and session.failure_code != (
                "storage_commit_mismatch"
            ):
                return session
            raise ValueError("upload session is not awaiting completion")
        info = await self._objects.stat(session.object_key)
        if info.size_bytes != session.expected_size or info.sha256 != session.expected_sha256:
            held = version.model_copy(
                update={
                    "state": DocumentState.HELD,
                    "available": False,
                    "failure_code": "storage_commit_mismatch",
                    "updated_at": self._clock(),
                }
            )
            failed_session = session.model_copy(
                update={"state": DocumentState.HELD, "failure_code": "storage_commit_mismatch"}
            )
            held = held.model_copy(update={"revision": version.revision + 1})
            failed_session = failed_session.model_copy(update={"revision": session.revision + 1})
            await self._commit_transition(
                session,
                version,
                failed_session,
                held,
                actor_id=actor_id,
                action="document.held",
            )
            raise ValueError("uploaded object does not match the declared size and hash")
        state = transition(session.state, DocumentState.RECEIVED)
        updated_session = session.model_copy(
            update={"state": state, "revision": session.revision + 1}
        )
        updated_version = version.model_copy(
            update={
                "state": state,
                "updated_at": self._clock(),
                "revision": version.revision + 1,
            }
        )
        await self._commit_transition(
            session,
            version,
            updated_session,
            updated_version,
            actor_id=actor_id,
            action="document.received",
        )
        await self._objects.revoke_upload(upload_id)
        return updated_session

    async def get_upload(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> UploadSession:
        session, version = await self._authorized_upload(upload_id)
        await self._access.authorize_read(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        return session

    async def list_versions(
        self,
        *,
        actor_id: str,
        document_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> tuple[DocumentVersion, ...]:
        versions = await self._metadata.list_versions(document_id)
        for version in versions:
            await self._access.authorize_read(
                actor_id=actor_id, actor_groups=actor_groups, version=version
            )
        return versions

    async def cancel_upload(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> UploadSession:
        session, version = await self._authorized_upload(upload_id)
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if session.state not in {
            DocumentState.CREATED,
            DocumentState.UPLOADING,
            DocumentState.RECEIVED,
        }:
            raise ValueError("processed content requires lineage-aware deletion")
        deleting = transition(session.state, DocumentState.DELETING)
        requested_at = self._clock()
        deleting_session = session.model_copy(
            update={
                "state": deleting,
                "failure_code": "cancelled",
                "revision": session.revision + 1,
            }
        )
        deleting_version = version.model_copy(
            update={
                "state": deleting,
                "available": False,
                "active": False,
                "failure_code": "cancelled",
                "updated_at": requested_at,
                "revision": version.revision + 1,
            }
        )
        await self._metadata.transition(
            deleting_session,
            deleting_version,
            expected_upload_state=session.state.value,
            expected_upload_revision=session.revision,
            expected_version_state=version.state.value,
            expected_version_revision=version.revision,
            event=self._deletion_event(
                deleting_session,
                deleting_version,
                actor_id=actor_id,
                requested_at=requested_at,
            ),
        )
        await self._objects.revoke_upload(upload_id)
        return deleting_session

    async def _authorized_upload(self, upload_id: UUID) -> tuple[UploadSession, DocumentVersion]:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        return session, version

    async def _commit_transition(
        self,
        previous_session: UploadSession,
        previous_version: DocumentVersion,
        session: UploadSession,
        version: DocumentVersion,
        *,
        actor_id: str,
        action: str,
    ) -> None:
        await self._metadata.transition(
            session,
            version,
            expected_upload_state=previous_session.state.value,
            expected_upload_revision=previous_session.revision,
            expected_version_state=previous_version.state.value,
            expected_version_revision=previous_version.revision,
            event=self._event(session, version, actor_id=actor_id, action=action),
        )

    def _event(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        actor_id: str,
        action: str,
    ) -> DocumentLifecycleEvent:
        record: dict[str, object] = {
            "action": action,
            "actor_id": actor_id,
            "collection_id": session.collection_id,
            "document_id": str(session.document_id),
            "version_id": str(session.version_id),
            "upload_id": str(session.upload_id),
            "source_sha256": session.expected_sha256,
            "state": session.state.value,
            "policy_version": session.retention.policy_version,
            "access_descriptor_ref": session.access.reference,
            "upload_revision": session.revision,
            "version_revision": version.revision,
        }
        identity = f"{action}:{version.version_id}:{version.revision}"
        return DocumentLifecycleEvent(
            event_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
            idempotency_key=identity,
            topic="object.event",
            key=str(session.document_id),
            payload={
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "action": action,
                "event_type": action,
                "correlation_id": str(session.upload_id),
                "idempotency_key": identity,
                "resource_id": str(session.document_id),
                "resource_type": "document",
                "document_id": str(session.document_id),
                "record": record,
            },
            created_at=self._clock(),
        )

    @staticmethod
    def _deletion_event(
        session: UploadSession,
        version: DocumentVersion,
        *,
        actor_id: str,
        requested_at: datetime,
    ) -> DocumentLifecycleEvent:
        identity = f"document.delete:{version.version_id}:{version.revision}"
        request = DocumentDeletionRequest(
            request_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
            idempotency_key=identity,
            document_id=version.document_id,
            version_id=version.version_id,
            upload_id=session.upload_id,
            requested_by=actor_id,
            expected_upload_revision=session.revision,
            expected_version_revision=version.revision,
            requested_at=requested_at,
        )
        return DocumentLifecycleEvent(
            event_id=request.request_id,
            idempotency_key=request.idempotency_key,
            topic="object.event",
            key=str(version.document_id),
            payload={
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "action": "document.deletion_requested",
                "event_type": "document.deletion_requested",
                "correlation_id": str(session.upload_id),
                "idempotency_key": identity,
                "resource_id": str(version.document_id),
                "resource_type": "document",
                "document_id": str(version.document_id),
                "deletion_request": request.model_dump(mode="json"),
            },
            created_at=requested_at,
        )


def _collection_segment(collection_id: str) -> str:
    return hashlib.sha256(collection_id.encode("utf-8")).hexdigest()[:16]
