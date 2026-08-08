"""Focused behavior contracts for extracted API and worker application code."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fdai_document_worker_service.adapters.activity import (
    PostgresDocumentActivitySink as WorkerDocumentActivitySink,
)
from fdai_document_worker_service.consumer import DocumentIngestionEventConsumer
from fdai_document_worker_service.processing import DocumentIngestionWorker
from fdai_document_worker_service.state_machine import (
    InvalidDocumentTransitionError as InvalidWorkerTransitionError,
)
from fdai_document_worker_service.state_machine import transition as worker_transition
from fdai_document_worker_service.supervisor import IngestionWorkerSupervisor
from fdai_ingestion_api_service.access import ClaimsDocumentAccessProvider
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
)
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresDocumentActivitySink as ApiDocumentActivitySink,
)
from fdai_ingestion_api_service.auth import Authenticator, GroupMapping
from fdai_ingestion_api_service.deletion import ApiDocumentDeletionService
from fdai_ingestion_api_service.http import IngestionGatewayConfig, build_app
from fdai_ingestion_api_service.ingestion import CreateUploadRequest, DocumentIngestionService
from fdai_ingestion_api_service.state_machine import (
    InvalidDocumentTransitionError as InvalidApiTransitionError,
)
from fdai_ingestion_api_service.state_machine import transition as api_transition
from fdai_service_contracts import (
    AUDIT_APPEND_LOCK_KEY,
    AUDIT_GENESIS_HASH,
    AccessDescriptor,
    DocumentDeletionRequest,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    IngestionCapabilities,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
    RetentionPolicy,
    SourceStorageMode,
    StoredObjectInfo,
    UploadGrant,
    UploadSession,
    canonical_audit_entry,
    next_audit_hash,
)
from starlette.testclient import TestClient


class MemoryMetadata:
    def __init__(self) -> None:
        self.uploads: dict[UUID, UploadSession] = {}
        self.versions: dict[tuple[UUID, UUID], DocumentVersion] = {}
        self.claims: dict[tuple[UUID, DocumentWorkerStage], DocumentWorkerClaim] = {}
        self.events: list[DocumentLifecycleEvent] = []

    async def create(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        event: DocumentLifecycleEvent | None = None,
    ) -> None:
        self.uploads[session.upload_id] = session
        self.versions[(version.document_id, version.version_id)] = version
        if event is not None:
            self.events.append(event)

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        return self.uploads[upload_id]

    async def save_upload(self, session: UploadSession) -> None:
        self.uploads[session.upload_id] = session

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        return self.versions[(document_id, version_id)]

    async def save_version(self, version: DocumentVersion) -> None:
        self.versions[(version.document_id, version.version_id)] = version

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
        current_session = self.uploads[session.upload_id]
        current_version = self.versions[(version.document_id, version.version_id)]
        if (
            current_session.state.value != expected_upload_state
            or current_session.revision != expected_upload_revision
            or current_version.state.value != expected_version_state
            or current_version.revision != expected_version_revision
        ):
            raise DocumentLifecycleConflictError("document lifecycle CAS conflict")
        if session.revision != expected_upload_revision + 1:
            raise ValueError("upload transition revision MUST increment exactly once")
        if version.revision != expected_version_revision + 1:
            raise ValueError("version transition revision MUST increment exactly once")
        self.uploads[session.upload_id] = session
        self.versions[(version.document_id, version.version_id)] = version
        self.events.append(event)

    async def transition_worker_stage(
        self,
        session: UploadSession,
        version: DocumentVersion,
        *,
        claim: DocumentWorkerClaim,
        expected_upload_state: str,
        expected_upload_revision: int,
        expected_version_state: str,
        expected_version_revision: int,
        event: DocumentLifecycleEvent,
    ) -> None:
        await self.assert_worker_stage_active(claim)
        await self.transition(
            session,
            version,
            expected_upload_state=expected_upload_state,
            expected_upload_revision=expected_upload_revision,
            expected_version_state=expected_version_state,
            expected_version_revision=expected_version_revision,
            event=event,
        )

    async def assert_worker_stage_active(self, claim: DocumentWorkerClaim) -> None:
        current = self.claims[(claim.upload_id, claim.stage)]
        if (
            current.owner != claim.owner
            or current.attempt_id != claim.attempt_id
            or current.revision != claim.revision
            or current.status is not DocumentWorkerClaimStatus.ACTIVE
            or current.lease_expires_at <= datetime.now(UTC)
        ):
            raise DocumentWorkerClaimConflictError("document worker claim conflict")

    async def enqueue_worker_event(
        self, event: DocumentLifecycleEvent, *, claim: DocumentWorkerClaim
    ) -> None:
        await self.assert_worker_stage_active(claim)
        self.events.append(event)

    async def enqueue_event(self, event: DocumentLifecycleEvent) -> None:
        self.events.append(event)

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        return tuple(value for (owner, _), value in self.versions.items() if owner == document_id)

    async def list_uploads_by_state(self, state: str, *, limit: int) -> tuple[UploadSession, ...]:
        return tuple(value for value in self.uploads.values() if value.state.value == state)[:limit]

    async def claim_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        lease_seconds: int,
    ) -> DocumentWorkerClaim | None:
        key = (upload_id, stage)
        now = datetime.now(UTC)
        current = self.claims.get(key)
        if current is not None:
            if current.status is DocumentWorkerClaimStatus.COMPLETED:
                return None
            if (
                current.status is DocumentWorkerClaimStatus.ACTIVE
                and current.lease_expires_at > now
            ):
                return None
            if current.attempt_id == attempt_id:
                return None
            claim = current.model_copy(
                update={
                    "owner": owner,
                    "attempt_id": attempt_id,
                    "revision": current.revision + 1,
                    "status": DocumentWorkerClaimStatus.ACTIVE,
                    "claimed_at": now,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "finished_at": None,
                }
            )
            self.claims[key] = claim
            return claim
        claim = DocumentWorkerClaim(
            upload_id=upload_id,
            stage=stage,
            owner=owner,
            attempt_id=attempt_id,
            revision=1,
            status=DocumentWorkerClaimStatus.ACTIVE,
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        self.claims[key] = claim
        return claim

    async def renew_worker_stage(self, *_args: object, **_kwargs: object) -> DocumentWorkerClaim:
        raise AssertionError("short operation must not renew")

    async def complete_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim:
        current = self.claims[(upload_id, stage)]
        await self.assert_worker_stage_active(current)
        if (
            current.owner != owner
            or current.attempt_id != attempt_id
            or current.revision != expected_revision
        ):
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        completed = current.model_copy(
            update={
                "revision": expected_revision + 1,
                "status": DocumentWorkerClaimStatus.COMPLETED,
                "finished_at": datetime.now(UTC),
            }
        )
        self.claims[(upload_id, stage)] = completed
        return completed

    async def release_worker_stage(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        *,
        owner: str,
        attempt_id: UUID,
        expected_revision: int,
    ) -> DocumentWorkerClaim:
        current = self.claims[(upload_id, stage)]
        await self.assert_worker_stage_active(current)
        if (
            current.owner != owner
            or current.attempt_id != attempt_id
            or current.revision != expected_revision
        ):
            raise DocumentWorkerClaimConflictError("document worker claim conflict")
        released = current.model_copy(
            update={
                "revision": expected_revision + 1,
                "status": DocumentWorkerClaimStatus.RELEASED,
                "finished_at": datetime.now(UTC),
            }
        )
        self.claims[(upload_id, stage)] = released
        return released


def test_audit_hash_contract_matches_existing_chain_snapshot() -> None:
    entry = {"action": "document.received", "document_id": "document-1"}
    assert AUDIT_APPEND_LOCK_KEY == 0x0FDA10AAAAAA01
    assert canonical_audit_entry(entry) == (
        '{"action":"document.received","document_id":"document-1"}'
    )
    assert next_audit_hash(AUDIT_GENESIS_HASH, entry) == (
        "50a84e0958e1f793b73da59aae11906b55af9177dacb23aa0e1ab8f35c56e31e"
    )


def test_deletion_request_requires_a_positive_expected_revision() -> None:
    now = datetime.now(UTC)
    request = DocumentDeletionRequest(
        request_id=uuid4(),
        idempotency_key="document.delete:version-1",
        document_id=uuid4(),
        version_id=uuid4(),
        upload_id=uuid4(),
        requested_by="operator",
        expected_upload_revision=1,
        expected_version_revision=1,
        requested_at=now,
    )

    assert request.expected_version_revision == 1
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "document-deletion-request",
        request.model_dump(mode="json"),
        version=request.schema_version,
    )
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        request.model_copy(update={"expected_version_revision": 0}).model_validate(
            request.model_dump() | {"expected_version_revision": 0}
        )


def test_api_and_worker_state_machines_enforce_transition_ownership() -> None:
    assert api_transition(DocumentState.UPLOADING, DocumentState.RECEIVED) is (
        DocumentState.RECEIVED
    )
    assert api_transition(DocumentState.READY, DocumentState.DELETING) is (DocumentState.DELETING)
    with pytest.raises(InvalidApiTransitionError):
        api_transition(DocumentState.RECEIVED, DocumentState.QUARANTINED)
    with pytest.raises(InvalidApiTransitionError):
        api_transition(DocumentState.DELETING, DocumentState.DELETED)

    assert worker_transition(DocumentState.RECEIVED, DocumentState.QUARANTINED) is (
        DocumentState.QUARANTINED
    )
    assert worker_transition(DocumentState.DELETING, DocumentState.DELETED) is (
        DocumentState.DELETED
    )
    with pytest.raises(InvalidWorkerTransitionError):
        worker_transition(DocumentState.CREATED, DocumentState.UPLOADING)
    with pytest.raises(InvalidWorkerTransitionError):
        worker_transition(DocumentState.READY, DocumentState.DELETING)


class MemoryObjects:
    def __init__(self) -> None:
        self.content: dict[str, bytes] = {}

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(session.upload_id, "memory://upload", session.expires_at)

    async def resume_upload(self, session: UploadSession) -> UploadGrant:
        return await self.issue_upload(session)

    async def put(self, object_key: str, content: bytes) -> StoredObjectInfo:
        self.content[object_key] = content
        return StoredObjectInfo(object_key, len(content), hashlib.sha256(content).hexdigest())

    async def put_stream(
        self,
        object_key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> StoredObjectInfo:
        content = b"".join([chunk async for chunk in chunks])
        self.content[object_key] = content
        return StoredObjectInfo(object_key, len(content), hashlib.sha256(content).hexdigest())

    async def stat(self, object_key: str) -> StoredObjectInfo:
        content = self.content[object_key]
        return StoredObjectInfo(object_key, len(content), hashlib.sha256(content).hexdigest())

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        yield self.content[object_key]

    async def revoke_upload(self, upload_id: UUID) -> None:
        return None

    async def delete(self, object_key: str) -> None:
        self.content.pop(object_key, None)

    async def delete_artifact(self, document_id: UUID, version_id: UUID) -> None:
        return None


class FailingGrantObjects(MemoryObjects):
    def __init__(self) -> None:
        super().__init__()
        self.revoked: list[UUID] = []

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        raise RuntimeError("grant unavailable")

    async def revoke_upload(self, upload_id: UUID) -> None:
        self.revoked.append(upload_id)


class Activity:
    def __init__(self) -> None:
        self.records: list[Mapping[str, object]] = []

    async def audit(self, record: Mapping[str, object]) -> None:
        self.records.append(record)

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        return None

    async def drain(self, *, limit: int = 100) -> int:
        return 0


class RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Mapping[str, object]]] = []
        self.dead_letters: list[tuple[str, str, Mapping[str, object], str]] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        self.published.append((topic, key, payload))

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
        reason: str,
    ) -> None:
        self.dead_letters.append((topic, key, payload, reason))


class FixedWorkerOutboxSink(WorkerDocumentActivitySink):
    def __init__(
        self,
        *,
        rows: list[dict[str, object]],
        event_bus: RecordingEventBus,
    ) -> None:
        super().__init__(dsn="postgresql://unused", event_bus=event_bus, event_topic="aw.events")
        self._rows = rows
        self.marked: list[UUID] = []

    async def _claim(self, limit: int) -> list[dict[str, object]]:
        return self._rows[:limit]

    async def _mark_published(self, event_id: UUID) -> None:
        self.marked.append(event_id)


class FixedApiOutboxSink(ApiDocumentActivitySink):
    def __init__(
        self,
        *,
        rows: list[dict[str, object]],
        publisher: RecordingEventBus,
    ) -> None:
        super().__init__(
            config=PostgresApiConfig(dsn="postgresql://unused"),
            publisher=publisher,
            topic="aw.events",
            pantheon_topic="aw.pantheon.objects",
        )
        self._rows = rows
        self.marked: list[UUID] = []

    async def _claim(self, limit: int) -> list[dict[str, object]]:
        return self._rows[:limit]

    async def _mark_published(self, event_id: UUID) -> None:
        self.marked.append(event_id)


@pytest.mark.asyncio
async def test_worker_outbox_uses_configured_transport_for_valid_and_poison_rows() -> None:
    event_bus = RecordingEventBus()
    poison_id = uuid4()
    valid = DocumentLifecycleEvent(
        event_id=uuid4(),
        idempotency_key="document.ready:version-1:7",
        topic="object.event",
        key="document-1",
        payload={"action": "document.ready"},
        created_at=datetime.now(UTC),
    )
    sink = FixedWorkerOutboxSink(
        rows=[
            {
                "event_id": poison_id,
                "topic": "object.event",
                "partition_key": "document-1",
                "payload": {"invalid": True},
            },
            {
                "event_id": valid.event_id,
                "topic": valid.topic,
                "partition_key": valid.key,
                "payload": valid.model_dump(mode="json"),
            },
        ],
        event_bus=event_bus,
    )

    assert await sink.drain() == 1
    assert event_bus.published == [("aw.events", valid.key, valid.payload)]
    assert event_bus.dead_letters == [
        (
            "aw.events",
            "document-1",
            {"outbox_event_id": str(poison_id)},
            "invalid_document_worker_outbox_event",
        )
    ]
    assert sink.marked == [poison_id, valid.event_id]


@pytest.mark.asyncio
async def test_api_outbox_dead_letters_poison_row_without_starving_valid_event() -> None:
    publisher = RecordingEventBus()
    poison_id = uuid4()
    valid = DocumentLifecycleEvent(
        event_id=uuid4(),
        idempotency_key="document.received:version-1:3",
        topic="object.event",
        key="document-1",
        payload={"action": "document.received"},
        created_at=datetime.now(UTC),
    )
    sink = FixedApiOutboxSink(
        rows=[
            {
                "event_id": poison_id,
                "topic": "object.event",
                "partition_key": "document-1",
                "payload": {"invalid": True},
            },
            {
                "event_id": valid.event_id,
                "topic": valid.topic,
                "partition_key": valid.key,
                "payload": valid.model_dump(mode="json"),
            },
        ],
        publisher=publisher,
    )

    assert await sink.drain() == 1
    assert publisher.published == [
        (
            "aw.pantheon.objects.dlq",
            "document-1",
            {
                "original_topic": "object.event",
                "reason": "invalid_document_api_outbox_event",
                "outbox_event_id": str(poison_id),
            },
        ),
        (
            "aw.pantheon.objects",
            valid.key,
            valid.payload | {"_fdai_logical_topic": valid.topic},
        ),
    ]
    assert sink.marked == [poison_id, valid.event_id]


class NoDeletion:
    async def delete(self, **_kwargs: object) -> DocumentVersion:
        raise AssertionError("delete is not expected")


@pytest.mark.asyncio
async def test_failed_upload_grant_does_not_publish_upload_created() -> None:
    metadata = MemoryMetadata()
    objects = FailingGrantObjects()
    service = DocumentIngestionService(
        access=ClaimsDocumentAccessProvider(),
        metadata=metadata,
        objects=objects,
        capabilities=IngestionCapabilities(
            supported_formats=("text",),
            storage_modes=(SourceStorageMode.MANAGED_COPY,),
            max_file_size=1024,
            max_batch_count=1,
            archives_enabled=False,
            policy_versions=("test",),
        ),
    )

    with pytest.raises(RuntimeError, match="grant unavailable"):
        await service.create_upload(
            actor_id="operator",
            actor_groups=frozenset({"role:Contributor"}),
            request=CreateUploadRequest(
                source_name="note.txt",
                collection_id="shared",
                media_type_hint="text/plain",
                expected_size=5,
                expected_sha256=hashlib.sha256(b"hello").hexdigest(),
                storage_mode=SourceStorageMode.MANAGED_COPY,
                purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
                access_descriptor_ref="collection:shared",
                reader_groups=(),
                retention_policy_version="test",
            ),
        )

    assert {session.state for session in metadata.uploads.values()} == {DocumentState.CREATED}
    assert metadata.events == []
    assert len(objects.revoked) == 0


@pytest.mark.asyncio
async def test_api_deletion_enqueues_worker_request_without_deleting_artifacts() -> None:
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    now = datetime.now(UTC)
    upload_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    access = AccessDescriptor(reference="collection:shared", collection_id="shared")
    retention = RetentionPolicy(policy_version="test")
    session = UploadSession(
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        actor_id="operator",
        source_name="note.txt",
        collection_id="shared",
        object_key="governed/source",
        media_type_hint="text/plain",
        expected_size=5,
        expected_sha256=hashlib.sha256(b"hello").hexdigest(),
        state=DocumentState.READY,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        access=access,
        retention=retention,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    version = DocumentVersion(
        document_id=document_id,
        version_id=version_id,
        upload_id=upload_id,
        source_name="note.txt",
        source_sha256=session.expected_sha256,
        size_bytes=5,
        media_type="text/plain",
        state=DocumentState.READY,
        access=access,
        retention=retention,
        purposes=session.purposes,
        uploader_id="operator",
        created_at=now,
        updated_at=now,
        active=True,
        available=True,
    )
    await metadata.create(session, version)
    objects.content[session.object_key] = b"hello"
    deletion = ApiDocumentDeletionService(
        access=ClaimsDocumentAccessProvider(),
        metadata=metadata,  # type: ignore[arg-type]
    )
    deleting = await deletion.delete(
        actor_id="operator",
        actor_groups=frozenset(),
        document_id=document_id,
        version_id=version_id,
    )

    assert deleting.state is DocumentState.DELETING
    assert session.object_key in objects.content
    assert len(metadata.events) == 1
    payload = metadata.events[0].payload
    assert payload["action"] == "document.deletion_requested"
    request = DocumentDeletionRequest.model_validate(payload["deletion_request"])
    assert request.expected_upload_revision == session.revision + 1
    assert request.expected_version_revision == version.revision + 1

    with pytest.raises(DocumentLifecycleConflictError, match="CAS conflict"):
        current_session = metadata.uploads[upload_id]
        current_version = metadata.versions[(document_id, version_id)]
        await metadata.transition(
            current_session.model_copy(update={"revision": current_session.revision + 1}),
            current_version.model_copy(update={"revision": current_version.revision + 1}),
            expected_upload_state=DocumentState.READY.value,
            expected_upload_revision=session.revision,
            expected_version_state=DocumentState.READY.value,
            expected_version_revision=version.revision,
            event=metadata.events[0],
        )


@pytest.mark.asyncio
async def test_api_cancel_hands_deletion_completion_to_worker() -> None:
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    content = b"hello"
    service = DocumentIngestionService(
        access=ClaimsDocumentAccessProvider(),
        metadata=metadata,
        objects=objects,
        capabilities=IngestionCapabilities(
            supported_formats=("text",),
            storage_modes=(SourceStorageMode.MANAGED_COPY,),
            max_file_size=1024,
            max_batch_count=1,
            archives_enabled=False,
            policy_versions=("test",),
        ),
    )
    session, _grant = await service.create_upload(
        actor_id="operator",
        actor_groups=frozenset({"role:Contributor"}),
        request=CreateUploadRequest(
            source_name="note.txt",
            collection_id="shared",
            media_type_hint="text/plain",
            expected_size=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            storage_mode=SourceStorageMode.MANAGED_COPY,
            purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
            access_descriptor_ref="collection:shared",
            reader_groups=(),
            retention_policy_version="test",
        ),
    )
    objects.content[session.object_key] = content

    cancelling = await service.cancel_upload(actor_id="operator", upload_id=session.upload_id)

    assert cancelling.state is DocumentState.DELETING
    assert session.object_key in objects.content
    event = metadata.events[-1]
    assert event.payload["action"] == "document.deletion_requested"
    request = DocumentDeletionRequest.model_validate(event.payload["deletion_request"])
    worker = DocumentIngestionWorker(
        metadata=metadata,
        objects=objects,
        malware=object(),  # type: ignore[arg-type]
        protection=object(),  # type: ignore[arg-type]
        extractor=object(),  # type: ignore[arg-type]
        artifacts=DeleteRecorder(),
        index=DeleteRecorder(),
    )

    claim = await metadata.claim_worker_stage(
        session.upload_id,
        DocumentWorkerStage.DELETION,
        owner="worker-a",
        attempt_id=uuid4(),
        lease_seconds=30,
    )
    assert claim is not None
    deleted = await worker.apply_deletion_request(request, lambda: claim)

    assert deleted.state is DocumentState.DELETED
    assert session.object_key not in objects.content


class DeleteRecorder:
    def __init__(self) -> None:
        self.deleted: list[tuple[UUID, UUID]] = []

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        self.deleted.append((document_id, version_id))


@pytest.mark.asyncio
async def test_worker_rejects_stale_request_and_claim_before_any_external_delete() -> None:
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    now = datetime.now(UTC)
    upload_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    access = AccessDescriptor(reference="collection:shared", collection_id="shared")
    retention = RetentionPolicy(policy_version="test")
    session = UploadSession(
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        actor_id="operator",
        source_name="note.txt",
        collection_id="shared",
        object_key="governed/source",
        media_type_hint="text/plain",
        expected_size=5,
        expected_sha256=hashlib.sha256(b"hello").hexdigest(),
        state=DocumentState.DELETING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        access=access,
        retention=retention,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        revision=3,
    )
    version = DocumentVersion(
        document_id=document_id,
        version_id=version_id,
        upload_id=upload_id,
        source_name="note.txt",
        source_sha256=session.expected_sha256,
        size_bytes=5,
        media_type="text/plain",
        state=DocumentState.DELETING,
        access=access,
        retention=retention,
        purposes=session.purposes,
        uploader_id="operator",
        created_at=now,
        updated_at=now,
        revision=4,
    )
    await metadata.create(session, version)
    objects.content[session.object_key] = b"hello"
    index = DeleteRecorder()
    artifacts = DeleteRecorder()
    worker = DocumentIngestionWorker(
        metadata=metadata,
        objects=objects,
        malware=object(),  # type: ignore[arg-type]
        protection=object(),  # type: ignore[arg-type]
        extractor=object(),  # type: ignore[arg-type]
        artifacts=artifacts,
        index=index,
    )
    stale = DocumentDeletionRequest(
        request_id=uuid4(),
        idempotency_key="document.delete:stale",
        document_id=document_id,
        version_id=version_id,
        upload_id=upload_id,
        requested_by="operator",
        expected_upload_revision=2,
        expected_version_revision=3,
        requested_at=now,
    )
    claim = await metadata.claim_worker_stage(
        upload_id,
        DocumentWorkerStage.DELETION,
        owner="worker-a",
        attempt_id=uuid4(),
        lease_seconds=30,
    )
    assert claim is not None

    with pytest.raises(DocumentLifecycleConflictError, match="stale document deletion"):
        await worker.apply_deletion_request(stale, lambda: claim)

    metadata.claims[(upload_id, DocumentWorkerStage.DELETION)] = claim.model_copy(
        update={"lease_expires_at": now - timedelta(seconds=1)}
    )
    reclaimed = await metadata.claim_worker_stage(
        upload_id,
        DocumentWorkerStage.DELETION,
        owner="worker-b",
        attempt_id=uuid4(),
        lease_seconds=30,
    )
    assert reclaimed is not None
    current = DocumentDeletionRequest(
        request_id=uuid4(),
        idempotency_key="document.delete:current",
        document_id=document_id,
        version_id=version_id,
        upload_id=upload_id,
        requested_by="operator",
        expected_upload_revision=session.revision,
        expected_version_revision=version.revision,
        requested_at=now,
    )
    with pytest.raises(DocumentWorkerClaimConflictError, match="claim conflict"):
        await worker.apply_deletion_request(current, lambda: claim)

    assert index.deleted == []
    assert artifacts.deleted == []
    assert session.object_key in objects.content
    assert metadata.events == []


def test_http_upload_content_and_complete_preserve_wire_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    service = DocumentIngestionService(
        access=ClaimsDocumentAccessProvider(),
        metadata=metadata,
        objects=objects,
        capabilities=IngestionCapabilities(
            supported_formats=("text",),
            storage_modes=(SourceStorageMode.MANAGED_COPY,),
            max_file_size=1024,
            max_batch_count=1,
            archives_enabled=False,
            policy_versions=("test",),
        ),
    )
    app = build_app(
        authenticator=Authenticator(
            verifier=lambda _token: {"oid": "operator", "roles": ["Owner"]},
            mapping=GroupMapping("r", "c", "a", "o", "b"),
        ),
        service=service,
        deletion=NoDeletion(),
        config=IngestionGatewayConfig(dev_mode=True, direct_upload=True),
    )
    content = b"hello"
    body = {
        "source_name": "note.txt",
        "collection_id": "shared",
        "media_type_hint": "text/plain",
        "expected_size": len(content),
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "storage_mode": "managed_copy",
        "purposes": ["knowledge_base"],
        "access_descriptor_ref": "collection:shared",
        "reader_groups": [],
        "retention_policy_version": "test",
    }
    with TestClient(app) as client:
        created = client.post("/ingestion/uploads", json=body)
        assert created.status_code == 201
        upload_id = created.json()["session"]["upload_id"]
        assert created.json()["upload"]["target"] == (f"/ingestion/uploads/{upload_id}/content")
        assert (
            client.put(f"/ingestion/uploads/{upload_id}/content", content=content).status_code
            == 204
        )
        completed = client.post(f"/ingestion/uploads/{upload_id}/complete")
        assert completed.status_code == 202
        assert completed.json()["state"] == "received"
        assert client.get(f"/ingestion/uploads/{upload_id}").json()["state"] == "received"
    assert [event.payload["action"] for event in metadata.events] == [
        "upload.created",
        "document.received",
    ]


@pytest.mark.asyncio
async def test_worker_claim_prevents_duplicate_operation() -> None:
    metadata = MemoryMetadata()
    upload_id = uuid4()
    calls = 0

    async def operation(_upload_id: UUID, _claim: object) -> object:
        nonlocal calls
        calls += 1
        return object()

    consumer = DocumentIngestionEventConsumer(
        event_bus=object(),  # type: ignore[arg-type]
        worker=object(),  # type: ignore[arg-type]
        metadata=metadata,
        activity=Activity(),
        topic="object.audit-entry",
        lease_seconds=30,
    )
    await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)
    await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)
    assert calls == 1
    assert metadata.claims[(upload_id, DocumentWorkerStage.INDEXING)].status is (
        DocumentWorkerClaimStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_worker_reclaim_rejects_stale_attempt_and_restart_completes_once() -> None:
    metadata = MemoryMetadata()
    upload_id = uuid4()
    stage = DocumentWorkerStage.INDEXING
    calls: list[str] = []
    first = DocumentIngestionEventConsumer(
        event_bus=object(),  # type: ignore[arg-type]
        worker=object(),  # type: ignore[arg-type]
        metadata=metadata,
        activity=Activity(),
        topic="object.audit-entry",
        worker_owner="worker-a",
        lease_seconds=30,
    )

    async def stale_operation(
        _upload_id: UUID, current_claim: Callable[[], DocumentWorkerClaim]
    ) -> object:
        stale = current_claim()
        metadata.claims[(upload_id, stage)] = stale.model_copy(
            update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        await metadata.assert_worker_stage_active(stale)
        calls.append("stale")
        return object()

    with pytest.raises(DocumentWorkerClaimConflictError, match="claim conflict"):
        await first._run_once(upload_id, stage, stale_operation)

    restarted = DocumentIngestionEventConsumer(
        event_bus=object(),  # type: ignore[arg-type]
        worker=object(),  # type: ignore[arg-type]
        metadata=metadata,
        activity=Activity(),
        topic="object.audit-entry",
        worker_owner="worker-b",
        lease_seconds=30,
    )

    async def recovered_operation(
        _upload_id: UUID, current_claim: Callable[[], DocumentWorkerClaim]
    ) -> object:
        await metadata.assert_worker_stage_active(current_claim())
        calls.append("recovered")
        return object()

    await restarted._run_once(upload_id, stage, recovered_operation)
    await first._run_once(upload_id, stage, recovered_operation)

    completed = metadata.claims[(upload_id, stage)]
    assert calls == ["recovered"]
    assert completed.owner == "worker-b"
    assert completed.revision == 3
    assert completed.status is DocumentWorkerClaimStatus.COMPLETED


class LoopService:
    async def run(self) -> None:
        await asyncio.Event().wait()

    async def run_index_commands(self) -> None:
        await asyncio.Event().wait()

    async def run_deletion_requests(self) -> None:
        await asyncio.Event().wait()

    async def drain_outbox(self) -> None:
        await asyncio.Event().wait()

    async def reconcile(self) -> None:
        await asyncio.Event().wait()


class WorkerRuntime:
    worker_service = LoopService()
    startup_checks: tuple = ()
    shutdown_callbacks: tuple = ()


@pytest.mark.asyncio
async def test_worker_supervisor_stops_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_health_start(_self: object) -> None:
        return None

    async def no_health_close(_self: object) -> None:
        return None

    monkeypatch.setattr(
        "fdai_document_worker_service.health.RuntimeHealthServer.start",
        no_health_start,
    )
    monkeypatch.setattr(
        "fdai_document_worker_service.health.RuntimeHealthServer.close",
        no_health_close,
    )
    stop = asyncio.Event()
    stop.set()
    supervisor = IngestionWorkerSupervisor(runtime=WorkerRuntime(), health_port=8000)
    assert await supervisor.run(stop=stop) == 0
    assert not supervisor.ready
