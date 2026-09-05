"""Upload lifecycle application service owned by the Document Ingestion API."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from fdai_service_contracts import (
    AccessDescriptor,
    DirectUploadStore,
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentDeletionRequest,
    DocumentDisposition,
    DocumentLifecycleEvent,
    DocumentNotFoundError,
    DocumentObjectStore,
    DocumentPurpose,
    DocumentScopeKind,
    DocumentState,
    DocumentUploadMetadataStore,
    DocumentVersion,
    IngestionCapabilities,
    RetentionPolicy,
    SourceStorageMode,
    StreamingUploadStore,
    UploadGrant,
    UploadSession,
    classify_document_intake,
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
_TEMPORARY_DISPOSITIONS = frozenset(
    {
        DocumentDisposition.SESSION_EPHEMERAL,
        DocumentDisposition.WORKSPACE_DRAFT,
    }
)
_MAX_TEMPORARY_RETENTION = timedelta(days=365)


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
    upload_id: UUID | None = None
    version_id: UUID | None = None
    connector_idempotency_key: str | None = None
    disposition: DocumentDisposition = DocumentDisposition.GOVERNED_KNOWLEDGE
    scope_kind: DocumentScopeKind | None = None
    scope_ref: str | None = None
    promoted_from_version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DocumentLifecyclePolicy:
    """Resolve server-owned temporary retention without accepting client deadlines."""

    session_ephemeral_duration: timedelta = timedelta(days=1)
    workspace_draft_duration: timedelta = timedelta(days=30)

    def __post_init__(self) -> None:
        for name, duration in (
            ("session_ephemeral_duration", self.session_ephemeral_duration),
            ("workspace_draft_duration", self.workspace_draft_duration),
        ):
            if duration <= timedelta(0) or duration > _MAX_TEMPORARY_RETENTION:
                raise ValueError(f"{name} MUST be in (0, 365 days]")

    def resolve(
        self,
        *,
        disposition: DocumentDisposition,
        policy_version: str,
        now: datetime,
    ) -> RetentionPolicy:
        """Return temporary deadlines or leave governed retention policy-owned."""
        if now.utcoffset() is None:
            raise ValueError("document lifecycle clock MUST include a timezone")
        duration = {
            DocumentDisposition.SESSION_EPHEMERAL: self.session_ephemeral_duration,
            DocumentDisposition.WORKSPACE_DRAFT: self.workspace_draft_duration,
        }.get(disposition)
        deadline = None if duration is None else now + duration
        return RetentionPolicy(
            policy_version=policy_version,
            source_expires_at=deadline,
            derived_expires_at=deadline,
        )


@dataclass(frozen=True, slots=True)
class TemporaryDocumentQuota:
    """Bound active temporary material reserved by one authenticated principal."""

    max_documents: int = 100
    max_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_documents < 1 or self.max_documents > 100_000:
            raise ValueError("temporary max_documents MUST be in [1, 100000]")
        if self.max_bytes < 1 or self.max_bytes > 10 * 1024 * 1024 * 1024 * 1024:
            raise ValueError("temporary max_bytes MUST be in [1, 10995116277760]")


@dataclass(frozen=True, slots=True)
class TemporaryDocumentUsage:
    """Current active temporary document count and reserved source bytes."""

    documents: int
    bytes: int

    def __post_init__(self) -> None:
        if self.documents < 0 or self.bytes < 0:
            raise ValueError("temporary document usage MUST NOT be negative")


class TemporaryDocumentQuotaExceededError(ValueError):
    """The principal's active temporary reservation would exceed a configured bound."""


@runtime_checkable
class DocumentCatalogMetadataStore(DocumentUploadMetadataStore, Protocol):
    """Read a bounded collection projection in addition to upload lifecycle records."""

    async def list_collection_versions(
        self, collection_id: str, *, limit: int
    ) -> tuple[DocumentVersion, ...]: ...


@runtime_checkable
class TemporaryDocumentMetadataStore(DocumentUploadMetadataStore, Protocol):
    """Count active temporary versions for principal-scoped admission control."""

    async def temporary_usage(self, actor_id: str) -> TemporaryDocumentUsage: ...

    async def create_with_temporary_quota(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        max_documents: int,
        max_bytes: int,
    ) -> None:
        """Atomically count and reserve one temporary upload."""
        ...


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
        lifecycle_policy: DocumentLifecyclePolicy | None = None,
        temporary_quota: TemporaryDocumentQuota | None = None,
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._capabilities = capabilities
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or uuid4
        self._upload_ttl = upload_ttl
        self._lifecycle_policy = lifecycle_policy or DocumentLifecyclePolicy()
        self._temporary_quota = temporary_quota or TemporaryDocumentQuota()

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
        fixed_ids = (request.upload_id, request.document_id, request.version_id)
        if any(value is not None for value in fixed_ids) and not all(
            value is not None for value in fixed_ids
        ):
            raise ValueError(
                "connector upload, document, and version ids MUST be supplied together"
            )
        if request.connector_idempotency_key is not None and not all(
            value is not None for value in fixed_ids
        ):
            raise ValueError("connector idempotency requires fixed upload identities")
        if request.document_id is None and request.supersedes_version_id is not None:
            raise ValueError("supersedes_version_id requires document_id")
        if (
            request.document_id is not None
            and request.supersedes_version_id is None
            and request.connector_idempotency_key is None
            and request.promoted_from_version_id is None
        ):
            raise ValueError("a replacement requires supersedes_version_id")
        if request.promoted_from_version_id is not None and (
            request.disposition is not DocumentDisposition.GOVERNED_KNOWLEDGE
            or request.supersedes_version_id is not None
        ):
            raise ValueError("promotion MUST create a new governed document")
        if request.document_id is not None and request.supersedes_version_id is not None:
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
        source_format = classify_document_intake(request.source_name, request.media_type_hint)
        if source_format.format_id not in self._capabilities.supported_formats:
            raise ValueError(f"document format {source_format.format_id} is unavailable")
        if request.storage_mode not in self._capabilities.storage_modes:
            raise ValueError("requested storage mode is unavailable")
        if not request.purposes:
            raise ValueError("at least one document purpose is required")
        if request.retention_policy_version not in self._capabilities.policy_versions:
            raise ValueError("requested retention policy version is unavailable")
        _validate_scope(request)

        now = self._clock()
        retention = self._lifecycle_policy.resolve(
            disposition=request.disposition,
            policy_version=request.retention_policy_version,
            now=now,
        )
        upload_id = request.upload_id or self._id_factory()
        document_id = request.document_id or self._id_factory()
        version_id = request.version_id or self._id_factory()
        access = AccessDescriptor(
            reference=request.access_descriptor_ref,
            collection_id=request.collection_id,
            reader_groups=request.reader_groups,
        )
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
            disposition=request.disposition,
            scope_kind=request.scope_kind,
            scope_ref=request.scope_ref,
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
            disposition=request.disposition,
            scope_kind=request.scope_kind,
            scope_ref=request.scope_ref,
            supersedes_version_id=request.supersedes_version_id,
            promoted_from_version_id=request.promoted_from_version_id,
        )
        if request.disposition in _TEMPORARY_DISPOSITIONS:
            if not isinstance(self._metadata, TemporaryDocumentMetadataStore):
                raise RuntimeError("temporary document quota metadata is unavailable")
            await self._metadata.create_with_temporary_quota(
                session,
                version,
                max_documents=self._temporary_quota.max_documents,
                max_bytes=self._temporary_quota.max_bytes,
            )
        else:
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

    async def promote_version(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
        collection_id: str,
        access_descriptor_ref: str,
        reader_groups: tuple[str, ...],
    ) -> UploadSession:
        """Copy one eligible temporary source into a replay-stable governed upload."""
        source = await self._metadata.get_version(document_id, version_id)
        source_session = await self._metadata.get_upload(source.upload_id)
        await self._access.authorize_delete(
            actor_id=actor_id,
            actor_groups=actor_groups,
            version=source,
        )
        await self._access.authorize_create(
            actor_id=actor_id,
            actor_groups=actor_groups,
            collection_id=collection_id,
        )
        if source.disposition not in _TEMPORARY_DISPOSITIONS:
            raise ValueError("only temporary or draft documents can be promoted")
        if (
            source.state not in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
            or not source.active
            or not source.available
        ):
            raise ValueError("only the current ready document version can be promoted")
        if source.retention.legal_hold:
            raise ValueError("a document subject to legal hold cannot be promoted")
        if collection_id != source.access.collection_id:
            raise ValueError("promotion cannot move source bytes between collections")

        upload_id = _stable_id(f"document.promote:upload:{source.version_id}:{collection_id}")
        promoted_document_id = _stable_id(
            f"document.promote:document:{source.version_id}:{collection_id}"
        )
        promoted_version_id = _stable_id(
            f"document.promote:version:{source.version_id}:{collection_id}"
        )
        try:
            target = await self._metadata.get_upload(upload_id)
            target_version = await self._metadata.get_version(
                promoted_document_id, promoted_version_id
            )
            if (
                target_version.promoted_from_version_id != source.version_id
                or target.collection_id != collection_id
                or target.expected_sha256 != source.source_sha256
            ):
                raise ValueError("promotion replay identity conflicts with stored metadata")
        except DocumentNotFoundError:
            try:
                target, _grant = await self.create_upload(
                    actor_id=actor_id,
                    actor_groups=actor_groups,
                    request=CreateUploadRequest(
                        source_name=source.source_name,
                        collection_id=collection_id,
                        media_type_hint=source.media_type,
                        expected_size=source.size_bytes,
                        expected_sha256=source.source_sha256,
                        storage_mode=source_session.storage_mode,
                        purposes=source.purposes,
                        access_descriptor_ref=access_descriptor_ref,
                        reader_groups=reader_groups,
                        retention_policy_version=source.retention.policy_version,
                        document_id=promoted_document_id,
                        upload_id=upload_id,
                        version_id=promoted_version_id,
                        disposition=DocumentDisposition.GOVERNED_KNOWLEDGE,
                        scope_kind=DocumentScopeKind.COLLECTION,
                        scope_ref=collection_id,
                        promoted_from_version_id=source.version_id,
                    ),
                )
            except ValueError as exc:
                if str(exc) != "document upload or version already exists":
                    raise
                target = await self._metadata.get_upload(upload_id)

        if target.state is DocumentState.CREATED:
            await self.resume_upload(
                actor_id=actor_id,
                actor_groups=actor_groups,
                upload_id=target.upload_id,
            )
            target = await self._metadata.get_upload(target.upload_id)
        if target.state is DocumentState.UPLOADING:
            await self.put_streaming_content(
                actor_id=actor_id,
                actor_groups=actor_groups,
                upload_id=target.upload_id,
                chunks=self._objects.read(source_session.object_key),
            )
            return await self.complete_upload(
                actor_id=actor_id,
                actor_groups=actor_groups,
                upload_id=target.upload_id,
            )
        if target.state in _COMPLETED_UPLOAD_STATES:
            return target
        raise ValueError("promoted upload is not replayable from its current state")

    async def resume_upload(
        self,
        *,
        actor_id: str,
        upload_id: UUID,
        actor_groups: frozenset[str] = frozenset(),
    ) -> UploadGrant:
        session, version = await self._authorized_upload(upload_id)
        if session.state not in {DocumentState.CREATED, DocumentState.UPLOADING}:
            raise ValueError("only an uploading session can be resumed")
        if session.expires_at <= self._clock():
            raise ValueError("upload session has expired")
        await self._access.authorize_delete(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if session.state is DocumentState.CREATED:
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
                    action="upload.recovered",
                )
            except BaseException:
                await self._objects.revoke_upload(upload_id)
                raise
            return grant
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

    async def list_documents(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        collection_id: str,
        limit: int,
    ) -> tuple[DocumentVersion, ...]:
        """Return authorized latest document versions for one logical collection."""
        if not isinstance(self._metadata, DocumentCatalogMetadataStore):
            raise RuntimeError("document catalog metadata is unavailable")
        candidates = await self._metadata.list_collection_versions(
            collection_id,
            limit=min(limit * 4, 400),
        )
        visible: list[DocumentVersion] = []
        for version in candidates:
            try:
                await self._access.authorize_read(
                    actor_id=actor_id,
                    actor_groups=actor_groups,
                    version=version,
                )
            except DocumentAccessDeniedError:
                continue
            visible.append(version)
            if len(visible) == limit:
                break
        return tuple(visible)

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


def _stable_id(identity: str) -> UUID:
    return UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16])


def _validate_scope(request: CreateUploadRequest) -> None:
    expected = {
        DocumentDisposition.SESSION_EPHEMERAL: DocumentScopeKind.CONVERSATION,
        DocumentDisposition.WORKSPACE_DRAFT: DocumentScopeKind.WORKSPACE,
        DocumentDisposition.REGULATED_RECORD: DocumentScopeKind.REGULATED,
    }.get(request.disposition)
    if expected is not None and (
        request.scope_kind is not expected or not (request.scope_ref or "").strip()
    ):
        raise ValueError(
            f"{request.disposition.value} documents MUST identify a {expected.value} scope"
        )
    if request.disposition is DocumentDisposition.GOVERNED_KNOWLEDGE and (
        request.scope_kind not in {None, DocumentScopeKind.COLLECTION}
        or request.scope_ref not in {None, request.collection_id}
    ):
        raise ValueError("governed knowledge MUST use its collection scope")
