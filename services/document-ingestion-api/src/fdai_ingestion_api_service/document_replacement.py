"""Resolve same-name Console uploads without mutating prior document versions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai_service_contracts import (
    DocumentAccessProvider,
    DocumentDisposition,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentScopeKind,
    DocumentState,
    DocumentUploadMetadataStore,
    DocumentVersion,
    SourceStorageMode,
    UploadSession,
)
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding


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
    cloud_knowledge: KnowledgeReleaseBinding | None = None
    replace_existing: bool = False


@runtime_checkable
class DocumentCatalogMetadataStore(DocumentUploadMetadataStore, Protocol):
    """Read bounded collection projections and resolve one exact-name replacement target."""

    async def list_collection_versions(
        self, collection_id: str, *, limit: int
    ) -> tuple[DocumentVersion, ...]: ...

    async def latest_collection_version_by_source_name(
        self, collection_id: str, source_name: str
    ) -> DocumentVersion | None: ...


@dataclass(frozen=True, slots=True)
class DocumentReplacementResolution:
    """Resolved request or an unchanged completed session that requires no write."""

    request: CreateUploadRequest
    unchanged_session: UploadSession | None = None


async def resolve_document_replacement(
    *,
    metadata: DocumentCatalogMetadataStore,
    access: DocumentAccessProvider,
    actor_id: str,
    actor_groups: frozenset[str],
    request: CreateUploadRequest,
    id_factory: Callable[[], UUID],
) -> DocumentReplacementResolution:
    """Resolve exact-name replacement under current read, create, and delete authority."""
    if any(
        value is not None
        for value in (
            request.document_id,
            request.supersedes_version_id,
            request.upload_id,
            request.version_id,
            request.connector_idempotency_key,
            request.promoted_from_version_id,
            request.cloud_knowledge,
        )
    ):
        raise ValueError("automatic replacement cannot use explicit document identities")
    await access.authorize_create(
        actor_id=actor_id,
        actor_groups=actor_groups,
        collection_id=request.collection_id,
    )
    previous = await metadata.latest_collection_version_by_source_name(
        request.collection_id,
        request.source_name,
    )
    if previous is None:
        return DocumentReplacementResolution(request=replace(request, replace_existing=False))
    await access.authorize_read(
        actor_id=actor_id,
        actor_groups=actor_groups,
        version=previous,
    )
    await access.authorize_delete(
        actor_id=actor_id,
        actor_groups=actor_groups,
        version=previous,
    )
    previous_session = await metadata.get_upload(previous.upload_id)
    if _is_unchanged(previous, previous_session, request):
        return DocumentReplacementResolution(
            request=replace(request, replace_existing=False),
            unchanged_session=previous_session,
        )
    return DocumentReplacementResolution(
        request=replace(
            request,
            document_id=previous.document_id,
            supersedes_version_id=previous.version_id,
            upload_id=id_factory(),
            version_id=id_factory(),
            replace_existing=False,
        )
    )


def _is_unchanged(
    previous: DocumentVersion,
    previous_session: UploadSession,
    request: CreateUploadRequest,
) -> bool:
    request_scope_kind = request.scope_kind
    request_scope_ref = request.scope_ref
    if request.disposition is DocumentDisposition.GOVERNED_KNOWLEDGE:
        request_scope_kind = request_scope_kind or DocumentScopeKind.COLLECTION
        request_scope_ref = request_scope_ref or request.collection_id
    return (
        request.disposition is DocumentDisposition.GOVERNED_KNOWLEDGE
        and previous.state in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
        and previous_session.state in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
        and previous.active
        and previous.available
        and previous.retention_state is DocumentRetentionState.LIVE
        and previous.source_name == request.source_name
        and previous.source_sha256 == request.expected_sha256
        and previous.size_bytes == request.expected_size
        and previous.purposes == request.purposes
        and previous.access.reference == request.access_descriptor_ref
        and frozenset(previous.access.reader_groups) == frozenset(request.reader_groups)
        and previous.retention.policy_version == request.retention_policy_version
        and previous.disposition is request.disposition
        and previous.scope_kind is request_scope_kind
        and previous.scope_ref == request_scope_ref
        and previous_session.storage_mode is request.storage_mode
    )
