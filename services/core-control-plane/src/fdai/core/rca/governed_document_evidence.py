"""Authorized document-search adapter for governed RCA evidence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fdai.core.operational_context import (
    DocumentEvidenceExcerpt,
    EvidenceTemporalScope,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadResult,
    OperationalEvidenceReadService,
    VerifiedEvidenceSourceReceipt,
    bind_evidence_item_source,
)
from fdai.core.rca.governed_knowledge_evidence import (
    GovernedDocumentRevision,
    GovernedKnowledgeEvidenceContext,
    GovernedKnowledgeEvidenceHoldError,
    governed_access_binding,
    governed_evidence_digest,
)
from fdai.shared.contracts import DocumentPurpose, DocumentState, DocumentVersion
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentMetadataStore,
    DocumentNotFoundError,
    DocumentSearch,
)
from fdai.shared.providers.knowledge import KnowledgeChunk

_READY_STATES = frozenset({DocumentState.READY, DocumentState.READY_WITH_WARNINGS})


class GovernedDocumentEvidenceReadAdapter:
    """Adapt authorized document search into an exact operational evidence read."""

    def __init__(
        self,
        *,
        search: DocumentSearch,
        metadata: DocumentMetadataStore,
        access: DocumentAccessProvider,
        clock: Callable[[], datetime],
        freshness_ceiling_seconds: int,
        max_bytes: int = 262_144,
    ) -> None:
        if freshness_ceiling_seconds < 1:
            raise ValueError("governed document freshness ceiling MUST be positive")
        self._search = search
        self._metadata = metadata
        self._access = access
        self._clock = clock
        self._freshness_ceiling_seconds = freshness_ceiling_seconds
        self._max_bytes = max_bytes

    async def read(
        self,
        *,
        query: str,
        context: GovernedKnowledgeEvidenceContext,
        limit: int,
    ) -> OperationalEvidenceReadResult:
        """Search only the authorized governed index and build one bound bundle."""

        if not query.strip():
            raise GovernedKnowledgeEvidenceHoldError("query_missing")
        if not 1 <= limit <= 20:
            raise ValueError("governed document evidence limit MUST be in [1, 20]")
        source = _GovernedDocumentEvidenceSource(
            search=self._search,
            metadata=self._metadata,
            access=self._access,
            clock=self._clock,
            freshness_ceiling_seconds=self._freshness_ceiling_seconds,
            query=query,
            context=context,
            limit=limit,
        )
        service = OperationalEvidenceReadService(
            source=source,
            clock=self._clock,
            max_items=limit,
            max_bytes=self._max_bytes,
        )
        return await service.read(
            context.read_request,
            authenticated_context=context.authenticated_context,
        )


class _GovernedDocumentEvidenceSource:
    """One-shot query-bound source used by OperationalEvidenceReadService."""

    def __init__(
        self,
        *,
        search: DocumentSearch,
        metadata: DocumentMetadataStore,
        access: DocumentAccessProvider,
        clock: Callable[[], datetime],
        freshness_ceiling_seconds: int,
        query: str,
        context: GovernedKnowledgeEvidenceContext,
        limit: int,
    ) -> None:
        self._search = search
        self._metadata = metadata
        self._access = access
        self._clock = clock
        self._freshness_ceiling_seconds = freshness_ceiling_seconds
        self._query = query
        self._context = context
        self._limit = limit

    async def collect(
        self,
        request: OperationalEvidenceReadRequest,
    ) -> OperationalEvidenceMaterial:
        if request != self._context.read_request:
            raise GovernedKnowledgeEvidenceHoldError("request_identity_mismatch")
        access_context = self._context.access_context
        try:
            hits = await self._search.search(
                self._query,
                collection_id=access_context.collection_id,
                allowed_access_refs=access_context.allowed_access_refs,
                k=self._limit,
            )
        except Exception as exc:
            raise GovernedKnowledgeEvidenceHoldError("search_unavailable") from exc

        documents: list[DocumentEvidenceExcerpt] = []
        pins = {revision.document_id: revision for revision in self._context.expected_revisions}
        for hit in hits:
            identity = _hit_identity(hit)
            pin = pins.get(identity.document_id)
            if pins and pin is None:
                continue
            if pin is not None and pin.version_id != identity.version_id:
                raise GovernedKnowledgeEvidenceHoldError("document_revision_mismatch")
            version = await self._load_version(identity.document_id, identity.version_id)
            _validate_version(
                version=version,
                hit=hit,
                context=self._context,
                pin=pin,
            )
            await self._authorize(version)
            documents.append(
                _document_excerpt(
                    hit=hit,
                    version=version,
                    request=request,
                    context=self._context,
                    recorded_at=_aware_now(self._clock),
                    freshness_ceiling_seconds=self._freshness_ceiling_seconds,
                )
            )

        return OperationalEvidenceMaterial(
            ontology_release_digest=request.ontology_release_digest,
            catalog_revision=request.catalog_revision,
            purpose=request.purpose,
            scope=request.scope,
            cutoff=request.cutoff,
            documents=tuple(documents),
        )

    async def _load_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        try:
            return await self._metadata.get_version(document_id, version_id)
        except DocumentNotFoundError as exc:
            raise GovernedKnowledgeEvidenceHoldError("document_missing") from exc
        except Exception as exc:
            raise GovernedKnowledgeEvidenceHoldError("metadata_unavailable") from exc

    async def _authorize(self, version: DocumentVersion) -> None:
        try:
            await self._access.authorize_read(
                actor_id=self._context.authenticated_context.principal_ref,
                actor_groups=self._context.access_context.actor_groups,
                version=version,
            )
        except DocumentAccessDeniedError as exc:
            raise GovernedKnowledgeEvidenceHoldError("document_unauthorized") from exc
        except Exception as exc:
            raise GovernedKnowledgeEvidenceHoldError("access_check_unavailable") from exc


@dataclass(frozen=True, slots=True)
class _HitIdentity:
    document_id: UUID
    version_id: UUID


def _hit_identity(hit: KnowledgeChunk) -> _HitIdentity:
    metadata = hit.metadata
    if metadata.get("governed_document") != "true":
        raise GovernedKnowledgeEvidenceHoldError("ungoverned_search_result")
    try:
        document_id = UUID(str(metadata["document_id"]))
        version_id = UUID(str(metadata["version_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise GovernedKnowledgeEvidenceHoldError("document_identity_missing") from exc
    expected_doc_id = f"governed:{document_id}:{version_id}"
    if hit.doc_id != expected_doc_id:
        raise GovernedKnowledgeEvidenceHoldError("document_revision_mismatch")
    return _HitIdentity(document_id=document_id, version_id=version_id)


def _validate_version(
    *,
    version: DocumentVersion,
    hit: KnowledgeChunk,
    context: GovernedKnowledgeEvidenceContext,
    pin: GovernedDocumentRevision | None,
) -> None:
    access_context = context.access_context
    metadata = hit.metadata
    if version.document_id != UUID(str(metadata["document_id"])) or version.version_id != UUID(
        str(metadata["version_id"])
    ):
        raise GovernedKnowledgeEvidenceHoldError("document_revision_mismatch")
    if version.state not in _READY_STATES or not version.available or not version.active:
        raise GovernedKnowledgeEvidenceHoldError("document_deleted_or_revoked")
    if DocumentPurpose.KNOWLEDGE_BASE not in version.purposes:
        raise GovernedKnowledgeEvidenceHoldError("document_purpose_mismatch")
    if (
        version.access.collection_id != access_context.collection_id
        or metadata.get("collection_id") != access_context.collection_id
    ):
        raise GovernedKnowledgeEvidenceHoldError("document_collection_mismatch")
    access_ref = version.access.reference
    if (
        access_ref not in access_context.allowed_access_refs
        or metadata.get("access_descriptor_ref") != access_ref
    ):
        raise GovernedKnowledgeEvidenceHoldError("document_unauthorized")
    if pin is not None and pin.source_sha256 != version.source_sha256:
        raise GovernedKnowledgeEvidenceHoldError("document_revision_mismatch")
    for field_name, value in (
        ("created_at", version.created_at),
        ("updated_at", version.updated_at),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise GovernedKnowledgeEvidenceHoldError(f"document_{field_name}_invalid")
    expires_at = version.retention.derived_expires_at
    if expires_at is not None and (expires_at.tzinfo is None or expires_at.utcoffset() is None):
        raise GovernedKnowledgeEvidenceHoldError("document_expiry_invalid")


def _document_excerpt(
    *,
    hit: KnowledgeChunk,
    version: DocumentVersion,
    request: OperationalEvidenceReadRequest,
    context: GovernedKnowledgeEvidenceContext,
    recorded_at: datetime,
    freshness_ceiling_seconds: int,
) -> DocumentEvidenceExcerpt:
    redaction_summary = _summary(hit.metadata.get("redaction_summary", "none"))
    conflicts = _summary(hit.metadata.get("evidence_conflicts", ""), required=False)
    document_revision = f"version:{version.version_id}:sha256:{version.source_sha256}"
    identity = {
        "document_revision": document_revision,
        "chunk_id": hit.chunk_id,
        "content_digest": governed_evidence_digest(hit.text),
    }
    evidence_ref = f"document:{governed_evidence_digest(identity)}"
    document_ref = (
        f"knowledge:{governed_evidence_digest((version.document_id.hex, document_revision))}"
    )
    excerpt_id = f"excerpt:{governed_evidence_digest(hit.chunk_id)}"
    source = VerifiedEvidenceSourceReceipt.create(
        ontology_release_digest=request.ontology_release_digest,
        catalog_revision=request.catalog_revision,
        document_revision=document_revision,
        source_identity="governed-document-index",
        source_revision=document_revision,
        authenticated_source="principal:document-ingestion",
        content_digest=governed_evidence_digest(hit.text),
        purpose=request.purpose,
        scope=request.scope,
        redaction_summary=redaction_summary,
        temporal_scope=EvidenceTemporalScope(
            effective_from=version.created_at,
            effective_to=version.retention.derived_expires_at,
            evidence_cutoff=version.updated_at,
            recorded_at=recorded_at,
        ),
        freshness_ceiling_seconds=freshness_ceiling_seconds,
        completeness=1.0,
        synthetic=False,
        conflicts=conflicts,
        verification_method="authorized-governed-document-search",
        verifier_identity="rca-governed-document-adapter",
        verification_receipt_ref=(
            f"document-access:{governed_evidence_digest(governed_access_binding(context))}"
        ),
    )
    item = DocumentEvidenceExcerpt(
        evidence_ref=evidence_ref,
        source=source,
        document_ref=document_ref,
        excerpt_id=excerpt_id,
        text=hit.text,
    )
    membership = {
        **governed_access_binding(context),
        "document_ref": document_ref,
        "excerpt_id": excerpt_id,
        "document_revision": document_revision,
        "redaction_summary": redaction_summary,
        "source_ref_digest": governed_evidence_digest(hit.source_ref),
    }
    return bind_evidence_item_source(item, membership_evidence=membership)


def _summary(value: object, *, required: bool = True) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise GovernedKnowledgeEvidenceHoldError("document_metadata_invalid")
    items = tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))
    if required and not items:
        raise GovernedKnowledgeEvidenceHoldError("document_redaction_missing")
    return items


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("governed document evidence clock MUST be timezone-aware")
    return value


__all__: Sequence[str] = ("GovernedDocumentEvidenceReadAdapter",)
