from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.delivery.ingestion_gateway.chat_evidence import UploaderDocumentEvidenceResolver
from fdai.delivery.read_api.routes.chat_document_evidence import ChatDocumentRef
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    RetentionPolicy,
)
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
)


class _Metadata:
    def __init__(self, version: DocumentVersion) -> None:
        self.version = version

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        assert document_id == self.version.document_id
        assert version_id == self.version.version_id
        return self.version


class _MissingMetadata:
    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        raise DocumentNotFoundError("document version was not found")


def _version(*, uploader: str = "operator", available: bool = True) -> DocumentVersion:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    return DocumentVersion(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        upload_id=UUID(int=3),
        source_name="evidence.txt",
        source_sha256="0" * 64,
        size_bytes=4,
        media_type="text/plain",
        observed_format="text",
        state=DocumentState.READY,
        access=AccessDescriptor(reference="acl", collection_id="collection"),
        retention=RetentionPolicy(policy_version="v1"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id=uploader,
        created_at=now,
        updated_at=now,
        available=available,
    )


async def test_uploader_resolver_returns_ready_immutable_citation() -> None:
    version = _version()
    resolver = UploaderDocumentEvidenceResolver(metadata=_Metadata(version))

    result = await resolver.resolve(
        principal_id="operator",
        references=(ChatDocumentRef(version.document_id, version.version_id),),
    )

    assert result == (f"doc:{version.document_id}:{version.version_id}",)


async def test_uploader_resolver_denies_another_principal() -> None:
    version = _version()
    resolver = UploaderDocumentEvidenceResolver(metadata=_Metadata(version))

    with pytest.raises(DocumentAccessDeniedError):
        await resolver.resolve(
            principal_id="different-operator",
            references=(ChatDocumentRef(version.document_id, version.version_id),),
        )


async def test_uploader_resolver_denies_unavailable_version() -> None:
    version = _version(available=False)
    resolver = UploaderDocumentEvidenceResolver(metadata=_Metadata(version))

    with pytest.raises(DocumentAccessDeniedError):
        await resolver.resolve(
            principal_id="operator",
            references=(ChatDocumentRef(version.document_id, version.version_id),),
        )


async def test_uploader_resolver_hides_missing_version_as_access_denied() -> None:
    resolver = UploaderDocumentEvidenceResolver(metadata=_MissingMetadata())

    with pytest.raises(DocumentAccessDeniedError):
        await resolver.resolve(
            principal_id="operator",
            references=(ChatDocumentRef(UUID(int=1), UUID(int=2)),),
        )
