from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fdai_ingestion_api_service.access import ClaimsDocumentAccessProvider
from fdai_ingestion_api_service.channel_attachment import (
    ChannelAttachmentAdmissionDeniedError,
    ChannelAttachmentConflictError,
    ChannelAttachmentIntakeService,
    ChannelAttachmentPolicy,
    ChannelAttachmentPrincipalManifest,
    ChannelAttachmentReservation,
)
from fdai_ingestion_api_service.ingestion import (
    DocumentIngestionService,
    TemporaryDocumentUsage,
)
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentOutcome,
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentNotFoundError,
    DocumentRetentionState,
    DocumentState,
    DocumentVersion,
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    IngestionCapabilities,
    SourceStorageMode,
    StewardResponsibility,
    StewardshipDraft,
    StoredObjectInfo,
    UploadGrant,
    UploadSession,
)
from fdai_service_contracts.compatibility import canonical_digest

NOW = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
CONTENT = b"bounded evidence"
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()
MANIFEST_DIGEST = f"sha256:{'a' * 64}"


class MemoryReservations:
    def __init__(self) -> None:
        self.records: dict[str, ChannelAttachmentReservation] = {}

    async def reserve(
        self, reservation: ChannelAttachmentReservation
    ) -> ChannelAttachmentReservation:
        stored = self.records.setdefault(reservation.request.handoff_id, reservation)
        if stored.request != reservation.request:
            raise ChannelAttachmentConflictError("injected reservation conflict")
        return stored

    async def get(self, handoff_id: str) -> ChannelAttachmentReservation:
        try:
            return self.records[handoff_id]
        except KeyError as exc:
            raise DocumentNotFoundError("reservation not found") from exc

    async def record_commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        commit: object,
    ) -> ChannelAttachmentReservation:
        stored = await self.get(handoff_id)
        if stored.request.request_digest != request_digest:
            raise ChannelAttachmentConflictError("injected request conflict")
        if stored.commit is not None:
            return stored
        updated = ChannelAttachmentReservation(
            request=stored.request,
            admission=stored.admission,
            commit=commit,  # type: ignore[arg-type]
        )
        self.records[handoff_id] = updated
        return updated


class MemoryMetadata:
    def __init__(self) -> None:
        self.uploads: dict[UUID, UploadSession] = {}
        self.versions: dict[tuple[UUID, UUID], DocumentVersion] = {}
        self.events: list[DocumentLifecycleEvent] = []

    async def create(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        event: DocumentLifecycleEvent | None = None,
    ) -> None:
        if session.upload_id in self.uploads:
            raise ValueError("document upload or version already exists")
        self.uploads[session.upload_id] = session
        self.versions[(version.document_id, version.version_id)] = version
        if event is not None:
            self.events.append(event)

    async def create_with_temporary_quota(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        max_documents: int,
        max_bytes: int,
    ) -> None:
        del max_documents, max_bytes
        await self.create(session, version)

    async def temporary_usage(self, actor_id: str) -> TemporaryDocumentUsage:
        uploads = tuple(item for item in self.uploads.values() if item.actor_id == actor_id)
        return TemporaryDocumentUsage(
            documents=len(uploads),
            bytes=sum(item.expected_size for item in uploads),
        )

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        try:
            return self.uploads[upload_id]
        except KeyError as exc:
            raise DocumentNotFoundError("upload not found") from exc

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        try:
            return self.versions[(document_id, version_id)]
        except KeyError as exc:
            raise DocumentNotFoundError("version not found") from exc

    async def transition(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        expected_upload_state: str,
        expected_upload_revision: int,
        expected_version_state: str,
        expected_version_revision: int,
        event: DocumentLifecycleEvent,
    ) -> None:
        current_session = await self.get_upload(session.upload_id)
        current_version = await self.get_version(version.document_id, version.version_id)
        if (
            current_session.state.value != expected_upload_state
            or current_session.revision != expected_upload_revision
            or current_version.state.value != expected_version_state
            or current_version.revision != expected_version_revision
        ):
            raise DocumentLifecycleConflictError("injected lifecycle conflict")
        self.uploads[session.upload_id] = session
        self.versions[(version.document_id, version.version_id)] = version
        self.events.append(event)

    async def enqueue_event(self, event: DocumentLifecycleEvent) -> None:
        self.events.append(event)

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        return tuple(
            version
            for (owner_id, _version_id), version in self.versions.items()
            if owner_id == document_id
        )

    async def list_uploads_by_state(self, state: str, *, limit: int) -> tuple[UploadSession, ...]:
        return tuple(upload for upload in self.uploads.values() if upload.state.value == state)[
            :limit
        ]


class MemoryObjects:
    def __init__(self) -> None:
        self.content: dict[str, bytes] = {}

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(session.upload_id, "memory://fixed", session.expires_at)

    async def resume_upload(self, session: UploadSession) -> UploadGrant:
        return await self.issue_upload(session)

    async def put_stream(
        self,
        object_key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> StoredObjectInfo:
        content = b"".join([chunk async for chunk in chunks])
        assert len(content) <= max_size
        self.content[object_key] = content
        return StoredObjectInfo(object_key, len(content), hashlib.sha256(content).hexdigest())

    async def stat(self, object_key: str) -> StoredObjectInfo:
        content = self.content[object_key]
        return StoredObjectInfo(object_key, len(content), hashlib.sha256(content).hexdigest())

    async def revoke_upload(self, upload_id: UUID) -> None:
        del upload_id


class DraftReader:
    def __init__(self) -> None:
        self.artifacts: dict[UUID, HandoverDraftArtifact] = {}
        self.delivered: set[UUID] = set()

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact:
        try:
            return self.artifacts[upload_id]
        except KeyError as exc:
            raise DocumentNotFoundError("draft not found") from exc

    async def governance_delivered(self, artifact: HandoverDraftArtifact) -> bool:
        return artifact.upload_id in self.delivered


async def _chunks() -> AsyncIterator[bytes]:
    yield CONTENT[:5]
    yield CONTENT[5:]


def _request(
    *,
    roles_digest: str = MANIFEST_DIGEST,
    purpose: str = "knowledge_base",
    principal: str = "principal-1",
    handoff_suffix: str = "b",
) -> ChannelAttachmentAdmissionRequest:
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "handoff_id": "channel-attachment-" + handoff_suffix * 64,
        "idempotency_key": f"message-1:attachment:{handoff_suffix}",
        "origin_digest": f"sha256:{'c' * 64}",
        "ordinal": 0,
        "attributed_principal_id": principal,
        "principal_manifest_digest": roles_digest,
        "conversation_ref": "00000000-0000-0000-0000-000000000010",
        "requested_purpose": purpose,
        "source_name": "evidence.txt",
        "media_type_hint": "text/plain",
        "declared_size": len(CONTENT),
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    return ChannelAttachmentAdmissionRequest.model_validate(
        {**material, "request_digest": canonical_digest(material)}
    )


def _intake(
    *,
    roles: frozenset[str] = frozenset({"Contributor"}),
    drafts: DraftReader | None = None,
    require_handover_governance: bool = False,
) -> tuple[ChannelAttachmentIntakeService, MemoryMetadata, MemoryReservations]:
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    access = ClaimsDocumentAccessProvider()
    ingestion = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=objects,
        capabilities=IngestionCapabilities(
            supported_formats=("text",),
            storage_modes=(SourceStorageMode.MANAGED_COPY,),
            max_file_size=1024,
            max_batch_count=8,
            archives_enabled=False,
            policy_versions=("channel-v1",),
        ),
        clock=lambda: NOW,
    )
    reservations = MemoryReservations()
    intake = ChannelAttachmentIntakeService(
        ingestion=ingestion,
        metadata=metadata,
        access=access,
        reservations=reservations,
        principals=ChannelAttachmentPrincipalManifest(
            roles_by_principal={"principal-1": roles},
            digest=MANIFEST_DIGEST,
        ),
        policy=ChannelAttachmentPolicy(
            collection_id="channel-evidence",
            access_descriptor_ref="collection:channel-evidence",
            reader_groups=("document-readers",),
            retention_policy_version="channel-v1",
            max_content_bytes=1024,
            require_handover_governance=require_handover_governance,
        ),
        handover_drafts=drafts,
        handover_governance=drafts,
        clock=lambda: NOW,
    )
    return intake, metadata, reservations


def _handover_artifact(commit: ChannelAttachmentCommitReceipt) -> HandoverDraftArtifact:
    return HandoverDraftArtifact(
        upload_id=commit.upload_id,
        document_id=commit.document_id,
        version_id=commit.version_id,
        draft=StewardshipDraft(
            outcome=HandoverDraftOutcome.DRAFTED,
            mappings=(
                HandoverMapping(
                    agent_name="Thor",
                    person=HandoverPerson(display_name="Example owner"),
                    responsibility=StewardResponsibility.ACCOUNTABLE,
                    confidence=1.0,
                    citations=(
                        HandoverSourceSpan(
                            doc_id="handover-fixture",
                            line=1,
                            quote="Thor ownership transfers to the example owner.",
                        ),
                    ),
                ),
            ),
        ),
        yaml="version: 2\nrevision: handover-fixture\n",
    )


def test_principal_manifest_parser_matches_edge_shape_and_rejects_duplicates() -> None:
    manifest = ChannelAttachmentPrincipalManifest.parse(
        '{"principal-1":{"scope_ref":"scope-1","roles":["Contributor"],"locale":"en"}}'
    )
    assert manifest.roles_for("principal-1") == frozenset({"Contributor"})
    assert manifest.digest.startswith("sha256:")
    with pytest.raises(ValueError, match="invalid JSON"):
        ChannelAttachmentPrincipalManifest.parse(
            '{"principal-1":{"scope_ref":"a","roles":["Reader"]},'
            '"principal-1":{"scope_ref":"b","roles":["Owner"]}}'
        )


async def test_admit_commit_and_replay_use_canonical_document_lifecycle() -> None:
    intake, metadata, _reservations = _intake()
    request = _request()

    admission = await intake.admit(request)
    assert await intake.admit(request) == admission
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    replay = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )

    assert replay == commit
    session = metadata.uploads[commit.upload_id]
    assert session.state is DocumentState.RECEIVED
    assert session.scope_ref == request.conversation_ref
    assert session.expected_sha256 == CONTENT_SHA256


async def test_status_replays_admission_until_commit_is_durable() -> None:
    intake, _metadata, _reservations = _intake()
    request = _request()
    admission = await intake.admit(request)

    observed = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )

    assert isinstance(observed, ChannelAttachmentAdmissionReceipt)
    assert observed == admission


async def test_status_replays_commit_until_metadata_is_observable() -> None:
    intake, metadata, _reservations = _intake()
    request = _request()
    await intake.admit(request)
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    metadata.uploads.pop(commit.upload_id)
    metadata.versions.pop((commit.document_id, commit.version_id))

    observed = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )

    assert isinstance(observed, ChannelAttachmentCommitReceipt)
    assert observed == commit


async def test_status_recovers_commit_after_upload_completion_crash() -> None:
    intake, _metadata, reservations = _intake()
    request = _request()
    admission = await intake.admit(request)
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    reservations.records[request.handoff_id] = ChannelAttachmentReservation(
        request=request,
        admission=admission,
        commit=None,
    )

    observed = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )

    recovered = reservations.records[request.handoff_id].commit
    assert recovered is not None
    assert recovered.observed_size == len(CONTENT)
    assert recovered.observed_sha256 == CONTENT_SHA256
    assert observed.commit_receipt_digest == recovered.receipt_digest
    assert recovered.upload_id == commit.upload_id


async def test_commit_replay_rejects_different_size_or_hash() -> None:
    intake, _metadata, _reservations = _intake()
    request = _request()
    await intake.admit(request)
    await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )

    with pytest.raises(ChannelAttachmentConflictError, match="replay content"):
        await intake.commit(
            handoff_id=request.handoff_id,
            request_digest=request.request_digest,
            observed_size=len(CONTENT),
            observed_sha256="f" * 64,
            chunks=_chunks(),
        )


async def test_existing_upload_hash_must_match_admitted_commit() -> None:
    intake, metadata, reservations = _intake()
    request = _request()
    admission = await intake.admit(request)
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    metadata.uploads[commit.upload_id] = metadata.uploads[commit.upload_id].model_copy(
        update={"expected_sha256": "f" * 64}
    )
    reservations.records[request.handoff_id] = ChannelAttachmentReservation(
        request=request,
        admission=admission,
        commit=None,
    )

    with pytest.raises(ChannelAttachmentConflictError, match="upload identity"):
        await intake.commit(
            handoff_id=request.handoff_id,
            request_digest=request.request_digest,
            observed_size=len(CONTENT),
            observed_sha256=CONTENT_SHA256,
            chunks=_chunks(),
        )


async def test_reader_and_stale_manifest_fail_before_upload_reservation() -> None:
    intake, metadata, _reservations = _intake(roles=frozenset({"Reader"}))
    with pytest.raises(ChannelAttachmentAdmissionDeniedError, match="Contributor"):
        await intake.admit(_request())
    assert metadata.uploads == {}

    contributor, contributor_metadata, _ = _intake()
    with pytest.raises(ChannelAttachmentAdmissionDeniedError, match="manifest"):
        await contributor.admit(_request(roles_digest=f"sha256:{'f' * 64}"))
    assert contributor_metadata.uploads == {}


async def test_same_handoff_with_different_request_conflicts() -> None:
    intake, _metadata, reservations = _intake()
    original = _request()
    await intake.admit(original)
    conflicting = original.model_copy(
        update={"source_name": "other.txt", "request_digest": f"sha256:{'f' * 64}"}
    )
    reservations.records[original.handoff_id] = reservations.records[original.handoff_id]

    with pytest.raises(ChannelAttachmentConflictError):
        await intake.admit(conflicting)


async def test_terminal_ready_requires_query_visible_version_and_exact_citation() -> None:
    intake, metadata, _ = _intake()
    request = _request()
    await intake.admit(request)
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    pending = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )
    assert pending.outcome is ChannelAttachmentOutcome.PENDING

    session = metadata.uploads[commit.upload_id]
    version = metadata.versions[(commit.document_id, commit.version_id)]
    metadata.uploads[commit.upload_id] = session.model_copy(
        update={"state": DocumentState.READY, "index_state": DocumentIndexState.ACTIVE}
    )
    metadata.versions[(commit.document_id, commit.version_id)] = version.model_copy(
        update={
            "state": DocumentState.READY,
            "index_state": DocumentIndexState.ACTIVE,
            "retention_state": DocumentRetentionState.LIVE,
            "active": True,
            "available": True,
        }
    )
    ready = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )
    assert ready.outcome is ChannelAttachmentOutcome.READY
    assert ready.citation == f"doc:{commit.document_id}:{commit.version_id}"


async def test_handover_waits_for_existing_draft_projection() -> None:
    drafts = DraftReader()
    intake, metadata, _ = _intake(drafts=drafts)
    request = _request(purpose="handover_bootstrap", handoff_suffix="d")
    await intake.admit(request)
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    session = metadata.uploads[commit.upload_id]
    version = metadata.versions[(commit.document_id, commit.version_id)]
    metadata.uploads[commit.upload_id] = session.model_copy(
        update={"state": DocumentState.READY, "index_state": DocumentIndexState.ACTIVE}
    )
    metadata.versions[(commit.document_id, commit.version_id)] = version.model_copy(
        update={
            "state": DocumentState.READY,
            "index_state": DocumentIndexState.ACTIVE,
            "active": True,
            "available": True,
        }
    )

    pending = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )
    drafts.artifacts[commit.upload_id] = _handover_artifact(commit)
    ready = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )
    assert pending.outcome is ChannelAttachmentOutcome.PENDING
    assert ready.outcome is ChannelAttachmentOutcome.READY


async def test_deployed_handover_waits_for_matching_governance_receipt() -> None:
    drafts = DraftReader()
    intake, metadata, _ = _intake(
        drafts=drafts,
        require_handover_governance=True,
    )
    request = _request(purpose="handover_bootstrap", handoff_suffix="e")
    await intake.admit(request)
    commit = await intake.commit(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
        observed_size=len(CONTENT),
        observed_sha256=CONTENT_SHA256,
        chunks=_chunks(),
    )
    session = metadata.uploads[commit.upload_id]
    version = metadata.versions[(commit.document_id, commit.version_id)]
    metadata.uploads[commit.upload_id] = session.model_copy(
        update={"state": DocumentState.READY, "index_state": DocumentIndexState.ACTIVE}
    )
    metadata.versions[(commit.document_id, commit.version_id)] = version.model_copy(
        update={
            "state": DocumentState.READY,
            "index_state": DocumentIndexState.ACTIVE,
            "active": True,
            "available": True,
        }
    )
    drafts.artifacts[commit.upload_id] = _handover_artifact(commit)

    pending = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )
    drafts.delivered.add(commit.upload_id)
    ready = await intake.status(
        handoff_id=request.handoff_id,
        request_digest=request.request_digest,
    )

    assert pending.outcome is ChannelAttachmentOutcome.PENDING
    assert ready.outcome is ChannelAttachmentOutcome.READY
