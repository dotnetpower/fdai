"""Governed source download tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai_ingestion_api_service.adapters.protection import PurviewRmsSourceDownloadAuthorizer
from fdai_ingestion_api_service.download import GovernedDocumentDownload
from fdai_ingestion_api_service.download_authorization import SourceDownloadAuthorization
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
async def test_download_allows_an_available_inactive_history_version() -> None:
    current, session = _records()
    version = current.model_copy(update={"active": False})
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

    assert metadata.events[0].payload["version_id"] == str(version.version_id)
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


class Protection:
    def __init__(self, on_authorize: Callable[[], None] | None = None) -> None:
        self.on_authorize = on_authorize

    async def authorize(self, **_kwargs: object) -> SourceDownloadAuthorization:
        if self.on_authorize is not None:
            self.on_authorize()
        return SourceDownloadAuthorization(
            request_id=UUID(int=5),
            canonical_receipt='{"allowed":true,"purpose":"governed_source_download"}',
            issued_at=_NOW,
            expires_at=_NOW + timedelta(seconds=30),
        )


def _protected_service(
    *,
    on_authorize: Callable[[], None] | None = None,
    clock: Callable[[], datetime] = lambda: _NOW,
) -> tuple[GovernedDocumentDownload, Metadata, Objects]:
    version, session = _records(protection=ProtectionState.RIGHTS_MANAGED_ACCESSIBLE)
    metadata = Metadata(version, session)
    objects = Objects()
    return (
        GovernedDocumentDownload(
            access=Access(),  # type: ignore[arg-type]
            metadata=metadata,  # type: ignore[arg-type]
            objects=objects,  # type: ignore[arg-type]
            protection=Protection(on_authorize),
            clock=clock,
            id_factory=lambda: UUID(int=4),
        ),
        metadata,
        objects,
    )


async def test_protected_source_requires_audited_purpose_bound_authorization() -> None:
    service, metadata, objects = _protected_service()
    result = await service.download(
        actor_id="reader",
        actor_groups=frozenset(),
        document_id=UUID(int=1),
        version_id=UUID(int=2),
    )
    assert objects.read_started is False
    audit = metadata.events[0].payload
    assert audit["authorization_purpose"] == "governed_source_download"
    receipt_json = audit["authorization_receipt_json"]
    assert isinstance(receipt_json, str)
    assert (
        audit["authorization_receipt_sha256"] == hashlib.sha256(receipt_json.encode()).hexdigest()
    )
    assert audit["authorization_request_id"] == str(UUID(int=5))
    restored = DocumentLifecycleEvent.model_validate_json(metadata.events[0].model_dump_json())
    assert restored.payload["authorization_receipt_json"] == receipt_json
    assert restored.payload["authorization_receipt_sha256"] == audit["authorization_receipt_sha256"]
    assert b"".join([chunk async for chunk in result.content]) == b"governed source"


async def test_source_revocation_during_provider_authorization_discloses_nothing() -> None:
    def revoke() -> None:
        metadata.version = metadata.version.model_copy(update={"available": False})

    service, metadata, objects = _protected_service(on_authorize=revoke)
    with pytest.raises(DocumentAccessDeniedError, match="binding changed"):
        await service.download(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert not metadata.events
    assert objects.read_started is False


async def test_source_revocation_before_stream_start_discloses_nothing() -> None:
    service, metadata, objects = _protected_service()
    result = await service.download(
        actor_id="reader",
        actor_groups=frozenset(),
        document_id=UUID(int=1),
        version_id=UUID(int=2),
    )
    metadata.version = metadata.version.model_copy(update={"available": False})
    with pytest.raises(DocumentAccessDeniedError, match="binding changed"):
        await anext(result.content)
    assert objects.read_started is False


async def test_expired_receipt_cannot_start_a_delayed_source_stream() -> None:
    now = _NOW
    service, _metadata, objects = _protected_service(clock=lambda: now)
    result = await service.download(
        actor_id="reader",
        actor_groups=frozenset(),
        document_id=UUID(int=1),
        version_id=UUID(int=2),
    )
    now += timedelta(seconds=30)
    with pytest.raises(DocumentAccessDeniedError, match="expired"):
        await anext(result.content)
    assert objects.read_started is False


@pytest.mark.parametrize(
    "protection",
    [
        ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED,
        ProtectionState.PASSWORD_ENCRYPTED,
        ProtectionState.UNSUPPORTED_PROTECTION,
        ProtectionState.UNKNOWN,
    ],
)
async def test_provider_cannot_enable_export_of_unavailable_protection_states(
    protection: ProtectionState,
) -> None:
    service, metadata, objects = _protected_service()
    metadata.version = metadata.version.model_copy(update={"protection_state": protection})
    with pytest.raises(DocumentAccessDeniedError, match="purpose-specific authorization"):
        await service.download(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert not metadata.events
    assert objects.read_started is False


async def test_authorization_expiry_stops_an_already_started_stream() -> None:
    now = _NOW
    service, _metadata, objects = _protected_service(clock=lambda: now)

    async def chunks(_key: str) -> AsyncIterator[bytes]:
        yield b"first"
        yield b"second"

    objects.read = chunks  # type: ignore[method-assign]
    result = await service.download(
        actor_id="reader",
        actor_groups=frozenset(),
        document_id=UUID(int=1),
        version_id=UUID(int=2),
    )
    assert await anext(result.content) == b"first"
    now += timedelta(seconds=30)
    with pytest.raises(DocumentAccessDeniedError, match="expired"):
        await anext(result.content)


async def test_revocation_stops_an_already_started_stream() -> None:
    service, metadata, objects = _protected_service()

    async def chunks(_key: str) -> AsyncIterator[bytes]:
        yield b"first"
        metadata.version = metadata.version.model_copy(update={"revision": 2})
        yield b"second"

    objects.read = chunks  # type: ignore[method-assign]
    result = await service.download(
        actor_id="reader",
        actor_groups=frozenset(),
        document_id=UUID(int=1),
        version_id=UUID(int=2),
    )
    assert await anext(result.content) == b"first"
    with pytest.raises(DocumentAccessDeniedError, match="binding changed"):
        await anext(result.content)


async def test_audit_unavailability_discloses_no_source_bytes() -> None:
    service, metadata, objects = _protected_service()

    async def fail_audit(_event: DocumentLifecycleEvent) -> None:
        raise RuntimeError("audit unavailable")

    metadata.enqueue_event = fail_audit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.download(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert objects.read_started is False


async def test_collection_access_is_rechecked_after_provider_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, metadata, objects = _protected_service()
    calls = 0

    async def current_access(**_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise DocumentAccessDeniedError("current collection access was revoked")

    monkeypatch.setattr(service._access, "authorize_read", current_access)
    with pytest.raises(DocumentAccessDeniedError, match="collection access was revoked"):
        await service.download(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert not metadata.events
    assert objects.read_started is False


async def test_unavailable_collection_authority_cannot_be_replaced_by_provider_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_called = False

    def provider() -> None:
        nonlocal provider_called
        provider_called = True

    service, metadata, objects = _protected_service(on_authorize=provider)

    async def denied(**_kwargs: object) -> None:
        raise DocumentAccessDeniedError("collection access denied")

    monkeypatch.setattr(service._access, "authorize_read", denied)
    with pytest.raises(DocumentAccessDeniedError, match="collection access denied"):
        await service.download(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert not provider_called
    assert not metadata.events
    assert not objects.read_started


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", UUID(int=8)),
        ("version_id", UUID(int=8)),
        ("upload_id", UUID(int=8)),
        ("expected_sha256", "c" * 64),
        ("expected_size", 20),
    ],
)
async def test_source_session_must_match_the_authorized_immutable_content(
    field: str, value: object
) -> None:
    service, metadata, objects = _protected_service()
    metadata.session = metadata.session.model_copy(update={field: value})
    with pytest.raises(DocumentAccessDeniedError, match="download binding changed"):
        await service.download(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert not metadata.events
    assert not objects.read_started


async def test_real_provider_receipt_flows_through_audit_and_source_stream() -> None:
    version, session = _records(protection=ProtectionState.RIGHTS_MANAGED_ACCESSIBLE)
    version = version.model_copy(
        update={"protection_provider_ref": "provider:document:1", "protection_policy_revision": 7}
    )
    metadata = Metadata(version, session)
    objects = Objects()

    class Token:
        token = "synthetic-provider-token"

    class Credential:
        async def get_token(self, *_scopes: str) -> Token:
            return Token()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["purpose"] == "governed_source_download"
        return httpx.Response(
            200,
            json={
                **body,
                "allowed": True,
                "expires_at": (_NOW + timedelta(seconds=30)).isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = PurviewRmsSourceDownloadAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=Credential(),
            client=client,
            clock=lambda: _NOW,
            id_factory=lambda: UUID(int=5),
        )
        service = GovernedDocumentDownload(
            access=Access(),  # type: ignore[arg-type]
            metadata=metadata,  # type: ignore[arg-type]
            objects=objects,  # type: ignore[arg-type]
            protection=provider,
            clock=lambda: _NOW,
        )
        result = await service.download(
            actor_id="reader",
            actor_groups=frozenset({"group"}),
            document_id=version.document_id,
            version_id=version.version_id,
        )
        receipt_json = metadata.events[0].payload["authorization_receipt_json"]
        assert isinstance(receipt_json, str)
        assert json.loads(receipt_json)["request_id"] == str(UUID(int=5))
        assert "synthetic-provider-token" not in receipt_json
        assert b"".join([chunk async for chunk in result.content]) == b"governed source"
