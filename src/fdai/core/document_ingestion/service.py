"""Upload-session service for the asynchronous document-ingestion plane."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fdai.core.document_ingestion.state_machine import transition
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    IngestionCapabilities,
    RetentionPolicy,
    SourceStorageMode,
    UploadSession,
)
from fdai.shared.providers.document_ingestion import (
    DirectUploadStore,
    DocumentAccessProvider,
    DocumentActivitySink,
    DocumentMetadataStore,
    DocumentObjectStore,
    UploadGrant,
)


@dataclass(frozen=True, slots=True)
class CreateUploadRequest:
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
    """Coordinates upload metadata; source bytes stay in object storage."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentMetadataStore,
        objects: DocumentObjectStore,
        activity: DocumentActivitySink,
        capabilities: IngestionCapabilities,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
        upload_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._activity = activity
        self._capabilities = capabilities
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or uuid4
        self._upload_ttl = upload_ttl

    @property
    def capabilities(self) -> IngestionCapabilities:
        return self._capabilities

    async def create_upload(
        self, *, actor_id: str, request: CreateUploadRequest
    ) -> tuple[UploadSession, UploadGrant]:
        await self._access.authorize_create(actor_id=actor_id, collection_id=request.collection_id)
        if request.document_id is None and request.supersedes_version_id is not None:
            raise ValueError("supersedes_version_id requires document_id")
        if request.document_id is not None:
            if request.supersedes_version_id is None:
                raise ValueError("a replacement requires supersedes_version_id")
            previous = await self._metadata.get_version(
                request.document_id, request.supersedes_version_id
            )
            await self._access.authorize_delete(actor_id=actor_id, version=previous)
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
            object_key=f"quarantine/{upload_id.hex}",
            media_type_hint=request.media_type_hint,
            expected_size=request.expected_size,
            expected_sha256=request.expected_sha256,
            state=DocumentState.UPLOADING,
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
            state=DocumentState.UPLOADING,
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
        await self._record(session, actor_id=actor_id, action="upload.created")
        return session, grant

    async def resume_upload(self, *, actor_id: str, upload_id: UUID) -> UploadGrant:
        session, version = await self._authorized_upload(actor_id=actor_id, upload_id=upload_id)
        if session.state is not DocumentState.UPLOADING:
            raise ValueError("only an uploading session can be resumed")
        if session.expires_at <= self._clock():
            raise ValueError("upload session has expired")
        await self._access.authorize_delete(actor_id=actor_id, version=version)
        return await self._objects.resume_upload(session)

    async def put_local_content(self, *, actor_id: str, upload_id: UUID, content: bytes) -> None:
        session, version = await self._authorized_upload(actor_id=actor_id, upload_id=upload_id)
        await self._access.authorize_delete(actor_id=actor_id, version=version)
        if session.state is not DocumentState.UPLOADING:
            raise ValueError("upload session is not accepting content")
        if len(content) > self._capabilities.max_file_size:
            raise ValueError("content exceeds the advertised file-size limit")
        if not isinstance(self._objects, DirectUploadStore):
            raise RuntimeError("direct upload is not supported by the object store")
        await self._objects.put(session.object_key, content)

    async def complete_upload(self, *, actor_id: str, upload_id: UUID) -> UploadSession:
        session, version = await self._authorized_upload(actor_id=actor_id, upload_id=upload_id)
        await self._access.authorize_delete(actor_id=actor_id, version=version)
        if session.state is not DocumentState.UPLOADING:
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
            await self._metadata.save_version(held)
            failed_session = session.model_copy(
                update={"state": DocumentState.HELD, "failure_code": "storage_commit_mismatch"}
            )
            await self._metadata.save_upload(failed_session)
            await self._record(failed_session, actor_id=actor_id, action="document.held")
            raise ValueError("uploaded object does not match the declared size and hash")
        received = transition(session.state, DocumentState.RECEIVED)
        session = session.model_copy(update={"state": received})
        version = version.model_copy(update={"state": received, "updated_at": self._clock()})
        await self._metadata.save_upload(session)
        await self._metadata.save_version(version)
        await self._objects.revoke_upload(upload_id)
        await self._record(session, actor_id=actor_id, action="document.received")
        return session

    async def get_upload(self, *, actor_id: str, upload_id: UUID) -> UploadSession:
        session, version = await self._authorized_upload(actor_id=actor_id, upload_id=upload_id)
        await self._access.authorize_read(actor_id=actor_id, version=version)
        return session

    async def list_versions(
        self, *, actor_id: str, document_id: UUID
    ) -> tuple[DocumentVersion, ...]:
        versions = await self._metadata.list_versions(document_id)
        for version in versions:
            await self._access.authorize_read(actor_id=actor_id, version=version)
        return versions

    async def cancel_upload(self, *, actor_id: str, upload_id: UUID) -> UploadSession:
        session, version = await self._authorized_upload(actor_id=actor_id, upload_id=upload_id)
        await self._access.authorize_delete(actor_id=actor_id, version=version)
        if session.state not in {
            DocumentState.CREATED,
            DocumentState.UPLOADING,
            DocumentState.RECEIVED,
        }:
            raise ValueError("processed content requires lineage-aware deletion")
        deleting = transition(session.state, DocumentState.DELETING)
        await self._objects.revoke_upload(upload_id)
        await self._objects.delete(session.object_key)
        deleted = transition(deleting, DocumentState.DELETED)
        now = self._clock()
        session = session.model_copy(update={"state": deleted, "failure_code": "cancelled"})
        version = version.model_copy(
            update={
                "state": deleted,
                "available": False,
                "active": False,
                "failure_code": "cancelled",
                "updated_at": now,
            }
        )
        await self._metadata.save_upload(session)
        await self._metadata.save_version(version)
        await self._record(session, actor_id=actor_id, action="document.deleted")
        return session

    async def _authorized_upload(
        self, *, actor_id: str, upload_id: UUID
    ) -> tuple[UploadSession, DocumentVersion]:
        session = await self._metadata.get_upload(upload_id)
        version = await self._metadata.get_version(session.document_id, session.version_id)
        return session, version

    async def _record(self, session: UploadSession, *, actor_id: str, action: str) -> None:
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
        }
        await self._activity.audit(record)
        await self._activity.publish(action, str(session.document_id), record)


__all__ = ["CreateUploadRequest", "DocumentIngestionService"]
