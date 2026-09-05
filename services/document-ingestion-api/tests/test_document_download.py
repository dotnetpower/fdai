"""Governed source download tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_ingestion_api_service.download import GovernedDocumentDownload
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentAccessDeniedError,
    DocumentLifecycleEvent,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    UploadSession,
)

_NOW = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)


class Access:
    async def authorize_read(self, **_kwargs: object) -> None:
        return None


class Metadata:
    def __init__(self, version: DocumentVersion, session: UploadSession) -> None:
        self.version = version
        self.session = session
        self.events: list[DocumentLifecycleEvent] = []

    async def get_version(self, _document_id: UUID, _version_id: UUID) -> DocumentVersion:
        return self.version

    async def get_upload(self, _upload_id: UUID) -> UploadSession:
        return self.session

    async def enqueue_event(self, event: DocumentLifecycleEvent) -> None:
        self.events.append(event)


class Objects:
    def __init__(self) -> None:
        self.read_started = False

    async def read(self, _object_key: str) -> AsyncIterator[bytes]:
        self.read_started = True
        yield b"governed source"


def _records(
    *, protection: ProtectionState = ProtectionState.NONE
) -> tuple[DocumentVersion, UploadSession]:
    access = AccessDescriptor(
        reference="collection:shared-knowledge",
        collection_id="shared-knowledge",
    )
    retention = RetentionPolicy(policy_version="v1")
    version = DocumentVersion(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        upload_id=UUID(int=3),
        source_name="guide.txt",
        source_sha256="a" * 64,
        size_bytes=15,
        media_type="text/plain",
        state=DocumentState.READY,
        protection_state=protection,
        access=access,
        retention=retention,
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="operator",
        created_at=_NOW,
        updated_at=_NOW,
        active=True,
        available=True,
    )
    session = UploadSession(
        upload_id=version.upload_id,
        document_id=version.document_id,
        version_id=version.version_id,
        actor_id="operator",
        source_name=version.source_name,
        collection_id=access.collection_id,
        object_key="quarantine/shared/source",
        media_type_hint=version.media_type,
        expected_size=version.size_bytes,
        expected_sha256=version.source_sha256,
        state=version.state,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=version.purposes,
        access=access,
        retention=retention,
        created_at=_NOW,
        expires_at=_NOW + timedelta(minutes=15),
    )
    return version, session


@pytest.mark.asyncio
async def test_download_audits_before_streaming_unprotected_source() -> None:
    version, session = _records()
    metadata = Metadata(version, session)
    objects = Objects()
    service = GovernedDocumentDownload(
        access=Access(),  # type: ignore[arg-type]
        metadata=metadata,  # type: ignore[arg-type]
        objects=objects,  # type: ignore[arg-type]
        clock=lambda: _NOW,
        id_factory=lambda: UUID(int=4),
    )

    result = await service.download(
        actor_id="operator",
        actor_groups=frozenset({"role:Owner"}),
        document_id=version.document_id,
        version_id=version.version_id,
    )

    assert objects.read_started is False
    assert metadata.events[0].payload["action"] == "document.source_download_requested"
    assert b"".join([chunk async for chunk in result.content]) == b"governed source"


@pytest.mark.asyncio
async def test_download_denies_protected_source_before_audit_or_read() -> None:
    version, session = _records(protection=ProtectionState.RIGHTS_MANAGED_ACCESSIBLE)
    metadata = Metadata(version, session)
    objects = Objects()
    service = GovernedDocumentDownload(
        access=Access(),  # type: ignore[arg-type]
        metadata=metadata,  # type: ignore[arg-type]
        objects=objects,  # type: ignore[arg-type]
    )

    with pytest.raises(DocumentAccessDeniedError, match="purpose-specific authorization"):
        await service.download(
            actor_id="operator",
            actor_groups=frozenset(),
            document_id=version.document_id,
            version_id=version.version_id,
        )

    assert metadata.events == []
    assert objects.read_started is False
