"""Focused behavior contracts for extracted API and worker application code."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fdai_document_worker_service.consumer import DocumentIngestionEventConsumer
from fdai_document_worker_service.supervisor import IngestionWorkerSupervisor
from fdai_ingestion_api_service.access import ClaimsDocumentAccessProvider
from fdai_ingestion_api_service.adapters.postgres import PostgresApiConfig
from fdai_ingestion_api_service.auth import Authenticator, GroupMapping
from fdai_ingestion_api_service.deletion import ApiDocumentDeletionService
from fdai_ingestion_api_service.http import IngestionGatewayConfig, build_app
from fdai_ingestion_api_service.ingestion import DocumentIngestionService
from fdai_service_contracts import (
    AUDIT_APPEND_LOCK_KEY,
    AUDIT_GENESIS_HASH,
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    IngestionCapabilities,
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

    async def create(self, session: UploadSession, version: DocumentVersion) -> None:
        self.uploads[session.upload_id] = session
        self.versions[(version.document_id, version.version_id)] = version

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        return self.uploads[upload_id]

    async def save_upload(self, session: UploadSession) -> None:
        self.uploads[session.upload_id] = session

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        return self.versions[(document_id, version_id)]

    async def save_version(self, version: DocumentVersion) -> None:
        self.versions[(version.document_id, version.version_id)] = version

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
        if key in self.claims:
            return None
        now = datetime.now(UTC)
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
        completed = current.model_copy(
            update={
                "revision": expected_revision + 1,
                "status": DocumentWorkerClaimStatus.COMPLETED,
                "finished_at": datetime.now(UTC),
            }
        )
        self.claims[(upload_id, stage)] = completed
        return completed

    async def release_worker_stage(self, *_args: object, **_kwargs: object) -> DocumentWorkerClaim:
        raise AssertionError("successful operation must not release")


def test_audit_hash_contract_matches_existing_chain_snapshot() -> None:
    entry = {"action": "document.received", "document_id": "document-1"}
    assert AUDIT_APPEND_LOCK_KEY == 0x0FDA10AAAAAA01
    assert canonical_audit_entry(entry) == (
        '{"action":"document.received","document_id":"document-1"}'
    )
    assert next_audit_hash(AUDIT_GENESIS_HASH, entry) == (
        "50a84e0958e1f793b73da59aae11906b55af9177dacb23aa0e1ab8f35c56e31e"
    )


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


class Activity:
    def __init__(self) -> None:
        self.records: list[Mapping[str, object]] = []

    async def audit(self, record: Mapping[str, object]) -> None:
        self.records.append(record)

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        return None


class NoDeletion:
    async def delete(self, **_kwargs: object) -> DocumentVersion:
        raise AssertionError("delete is not expected")


@pytest.mark.asyncio
async def test_api_owned_deletion_records_terminal_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    activity = Activity()
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
        objects=objects,  # type: ignore[arg-type]
        database=PostgresApiConfig(dsn="postgresql://unused"),
        activity=activity,
    )

    async def no_chunks(_document_id: UUID, _version_id: UUID) -> None:
        return None

    monkeypatch.setattr(deletion, "_delete_chunks", no_chunks)
    deleted = await deletion.delete(
        actor_id="operator",
        actor_groups=frozenset(),
        document_id=document_id,
        version_id=version_id,
    )
    assert deleted.state is DocumentState.DELETED
    assert session.object_key not in objects.content
    assert [record["action"] for record in activity.records] == ["document.deleted"]


def test_http_upload_content_and_complete_preserve_wire_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    metadata = MemoryMetadata()
    objects = MemoryObjects()
    activity = Activity()
    service = DocumentIngestionService(
        access=ClaimsDocumentAccessProvider(),
        metadata=metadata,
        objects=objects,
        activity=activity,
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
    assert [record["action"] for record in activity.records] == [
        "upload.created",
        "document.received",
    ]


@pytest.mark.asyncio
async def test_worker_claim_prevents_duplicate_operation() -> None:
    metadata = MemoryMetadata()
    upload_id = uuid4()
    calls = 0

    async def operation(_upload_id: UUID) -> object:
        nonlocal calls
        calls += 1
        return object()

    consumer = DocumentIngestionEventConsumer(
        event_bus=object(),  # type: ignore[arg-type]
        worker=object(),  # type: ignore[arg-type]
        metadata=metadata,
        topic="object.audit-entry",
        lease_seconds=30,
    )
    await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)
    await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)
    assert calls == 1
    assert metadata.claims[(upload_id, DocumentWorkerStage.INDEXING)].status is (
        DocumentWorkerClaimStatus.COMPLETED
    )


class LoopService:
    async def run(self) -> None:
        await asyncio.Event().wait()

    async def run_index_commands(self) -> None:
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
