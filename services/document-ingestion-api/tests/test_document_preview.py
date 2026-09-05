"""Governed document preview authorization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fdai_ingestion_api_service.adapters.protection import (
    PurviewRmsPreviewAuthorizer,
)
from fdai_ingestion_api_service.preview import GovernedDocumentPreview
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentAccessDeniedError,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    ProviderUnavailableError,
    RetentionPolicy,
    StructuralUnit,
)


class Access:
    async def authorize_read(self, **_kwargs: object) -> None:
        return None


class Metadata:
    def __init__(self, version: DocumentVersion) -> None:
        self.version = version

    async def get_version(self, _document_id: UUID, _version_id: UUID) -> DocumentVersion:
        return self.version


class Artifacts:
    def __init__(self, envelope: DocumentEnvelope) -> None:
        self.envelope = envelope
        self.read = False

    async def read_artifact(self, _document_id: UUID, _version_id: UUID) -> DocumentEnvelope:
        self.read = True
        return self.envelope


class Protection:
    def __init__(self, *, deny: bool = False) -> None:
        self.deny = deny

    async def authorize(self, **_kwargs: object) -> None:
        if self.deny:
            raise DocumentAccessDeniedError("denied")


class Credential:
    async def get_token(self, *_scopes: str) -> object:
        return SimpleNamespace(token="provider-token")


def _version(**updates: object) -> DocumentVersion:
    now = datetime.now(tz=UTC)
    values: dict[str, object] = {
        "document_id": UUID(int=1),
        "version_id": UUID(int=2),
        "upload_id": UUID(int=3),
        "source_name": "guide.pdf",
        "source_sha256": "a" * 64,
        "size_bytes": 100,
        "media_type": "application/pdf",
        "state": DocumentState.READY,
        "protection_state": ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
        "protection_provider_ref": "provider:document:1",
        "protection_policy_revision": 7,
        "access": AccessDescriptor(
            reference="collection:shared-knowledge",
            collection_id="shared-knowledge",
        ),
        "retention": RetentionPolicy(policy_version="v1"),
        "purposes": (DocumentPurpose.KNOWLEDGE_BASE,),
        "uploader_id": "operator",
        "created_at": now,
        "updated_at": now,
        "active": True,
        "available": True,
    }
    values.update(updates)
    return DocumentVersion.model_validate(values)


def _envelope() -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        source_sha256="a" * 64,
        media_type="application/pdf",
        observed_format="pdf",
        size_bytes=100,
        collection_id="shared-knowledge",
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        protection_state=ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
        access_descriptor_ref="collection:shared-knowledge",
        units=(
            StructuralUnit(
                unit_id="page-1",
                kind="page",
                locator="page:1",
                text="Authorized extracted text",
            ),
        ),
        extractor_name="test",
        extractor_version="1",
    )


async def test_preview_checks_both_authorizers_before_reading_artifact() -> None:
    artifacts = Artifacts(_envelope())
    preview = GovernedDocumentPreview(
        access=Access(),  # type: ignore[arg-type]
        metadata=Metadata(_version()),  # type: ignore[arg-type]
        artifacts=artifacts,
        protection=Protection(),  # type: ignore[arg-type]
    )

    envelope = await preview.preview(
        actor_id="reader",
        actor_groups=frozenset({"group"}),
        document_id=UUID(int=1),
        version_id=UUID(int=2),
    )

    assert artifacts.read is True
    assert envelope.units[0].locator == "page:1"


async def test_denied_or_revoked_preview_never_reads_artifact() -> None:
    artifacts = Artifacts(_envelope())
    denied = GovernedDocumentPreview(
        access=Access(),  # type: ignore[arg-type]
        metadata=Metadata(_version()),  # type: ignore[arg-type]
        artifacts=artifacts,
        protection=Protection(deny=True),  # type: ignore[arg-type]
    )
    with pytest.raises(DocumentAccessDeniedError, match="denied"):
        await denied.preview(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert artifacts.read is False

    revoked = GovernedDocumentPreview(
        access=Access(),  # type: ignore[arg-type]
        metadata=Metadata(_version(active=False, available=False)),  # type: ignore[arg-type]
        artifacts=artifacts,
        protection=Protection(),  # type: ignore[arg-type]
    )
    with pytest.raises(DocumentAccessDeniedError, match="not available"):
        await revoked.preview(
            actor_id="reader",
            actor_groups=frozenset(),
            document_id=UUID(int=1),
            version_id=UUID(int=2),
        )
    assert artifacts.read is False


async def test_purview_preview_authorization_binds_actor_and_document() -> None:
    version = _version()

    def handler(request: httpx.Request) -> httpx.Response:
        request_payload = __import__("json").loads(request.content)
        return httpx.Response(200, json={**request_payload, "allowed": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = PurviewRmsPreviewAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        await authorizer.authorize(
            actor_id="reader",
            actor_groups=frozenset({"group"}),
            version=version,
        )


async def test_purview_preview_rejects_unbound_decision() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"allowed": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = PurviewRmsPreviewAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="binding failed"):
            await authorizer.authorize(
                actor_id="reader",
                actor_groups=frozenset(),
                version=_version(),
            )
