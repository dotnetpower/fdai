"""Principal-scoped governed document evidence tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalEvidenceReadRequest,
)
from fdai.core.rca import (
    Citation,
    CitationKind,
    KnowledgeEvidenceGatherer,
    RcaCoordinator,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.governed_document_evidence import GovernedDocumentEvidenceReadAdapter
from fdai.core.rca.governed_knowledge_evidence import (
    GovernedDocumentAccessContext,
    GovernedDocumentEvidenceReader,
    GovernedDocumentRevision,
    GovernedKnowledgeEvidenceContext,
    GovernedKnowledgeEvidenceGatherer,
    GovernedKnowledgeEvidenceHoldError,
    GovernedKnowledgeEvidenceResult,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    RetentionPolicy,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.document_ingestion import (
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentMetadataStore,
    DocumentNotFoundError,
)
from fdai.shared.providers.knowledge import KnowledgeChunk

NOW = datetime(2026, 9, 4, 2, 30, tzinfo=UTC)
DOCUMENT_ID = UUID(int=1)
VERSION_ID = UUID(int=2)
OTHER_VERSION_ID = UUID(int=3)
SOURCE_SHA = "a" * 64
RELEASE = "sha256:" + "b" * 64
PRINCIPAL_SCOPE = "sha256:" + "c" * 64


class _Search:
    def __init__(self, hits: Sequence[KnowledgeChunk]) -> None:
        self.hits = tuple(hits)
        self.calls: list[tuple[str, str, frozenset[str], int]] = []

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> Sequence[KnowledgeChunk]:
        self.calls.append((query, collection_id, allowed_access_refs, k))
        return self.hits[:k]


class _Metadata:
    def __init__(self, version: DocumentVersion | None) -> None:
        self.version = version

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        if (
            self.version is None
            or self.version.document_id != document_id
            or self.version.version_id != version_id
        ):
            raise DocumentNotFoundError("version unavailable")
        return self.version


class _Access:
    def __init__(self, *, denied: bool = False) -> None:
        self.denied = denied
        self.calls: list[tuple[str, frozenset[str], UUID]] = []

    async def authorize_read(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        self.calls.append((actor_id, actor_groups, version.version_id))
        if self.denied:
            raise DocumentAccessDeniedError("revoked")


def _version(
    *,
    state: DocumentState = DocumentState.READY,
    available: bool = True,
    active: bool = True,
    updated_at: datetime = NOW - timedelta(minutes=1),
) -> DocumentVersion:
    return DocumentVersion(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        upload_id=UUID(int=4),
        source_name="runbook.txt",
        source_sha256=SOURCE_SHA,
        size_bytes=128,
        media_type="text/plain",
        observed_format="text",
        state=state,
        access=AccessDescriptor(
            reference="collection:operations",
            collection_id="operations",
            reader_groups=("group:responders",),
        ),
        retention=RetentionPolicy(policy_version="retention-v1"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="principal:author",
        created_at=NOW - timedelta(hours=1),
        updated_at=updated_at,
        active=active,
        available=available,
    )


def _hit(
    *,
    version_id: UUID = VERSION_ID,
    redaction_summary: str = "none",
    conflicts: str = "",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        doc_id=f"governed:{DOCUMENT_ID}:{version_id}",
        chunk_id=f"governed:{DOCUMENT_ID}:{version_id}:paragraph-1:0",
        text="Check dependency saturation before recovery.",
        source_ref=f"document://{DOCUMENT_ID}/versions/{version_id}#paragraph-1",
        score=0.9,
        metadata={
            "governed_document": "true",
            "document_id": str(DOCUMENT_ID),
            "version_id": str(version_id),
            "collection_id": "operations",
            "access_descriptor_ref": "collection:operations",
            "redaction_summary": redaction_summary,
            "evidence_conflicts": conflicts,
        },
    )


def _principal() -> AuthenticatedPrincipalContext:
    authority = SecuredQueryReceiptAuthority(now=lambda: NOW)
    return AuthenticatedPrincipalContext(
        principal_ref="principal:responder",
        principal_scope_digest=PRINCIPAL_SCOPE,
        purpose="incident-review",
        receipt_authority=authority,
        invocation_context=FunctionInvocationContext(
            caller_agent="Forseti",
            caller_role=CeilingRole.READER,
            purposes=("incident-review",),
        ),
        verification_context=authority.verification_context,
    )


def _context(
    *,
    expected_revisions: tuple[GovernedDocumentRevision, ...] = (),
) -> GovernedKnowledgeEvidenceContext:
    return GovernedKnowledgeEvidenceContext(
        read_request=OperationalEvidenceReadRequest(
            ontology_release_digest=RELEASE,
            catalog_revision="catalog-r1",
            purpose="incident-review",
            scope=("resource:example",),
            cutoff=NOW,
        ),
        authenticated_context=_principal(),
        access_context=GovernedDocumentAccessContext(
            collection_id="operations",
            access_context_ref="access-context:incident-review",
            allowed_access_refs=frozenset({"collection:operations"}),
            actor_groups=frozenset({"group:responders"}),
        ),
        expected_revisions=expected_revisions,
    )


def _adapter(
    *,
    search: _Search,
    metadata: _Metadata,
    access: _Access,
    freshness_ceiling_seconds: int = 3600,
) -> GovernedDocumentEvidenceReadAdapter:
    return GovernedDocumentEvidenceReadAdapter(
        search=search,
        metadata=cast(DocumentMetadataStore, metadata),
        access=cast(DocumentAccessProvider, access),
        clock=lambda: NOW,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
    )


async def test_gatherer_binds_principal_access_revision_redaction_and_opaque_citation() -> None:
    search = _Search((_hit(),))
    access = _Access()
    gatherer = GovernedKnowledgeEvidenceGatherer(
        reader=_adapter(search=search, metadata=_Metadata(_version()), access=access)
    )

    result = await gatherer.gather(query="dependency saturation", context=_context())

    assert result.hold_required is False
    assert result.bundle_id is not None
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.kind is CitationKind.KNOWLEDGE
    assert citation.ref.startswith("knowledge:sha256:")
    assert "document://" not in citation.ref
    assert "Check dependency" not in citation.ref
    assert search.calls == [
        (
            "dependency saturation",
            "operations",
            frozenset({"collection:operations"}),
            5,
        )
    ]
    assert access.calls == [("principal:responder", frozenset({"group:responders"}), VERSION_ID)]


@pytest.mark.parametrize(
    ("version", "hit", "freshness", "hold"),
    [
        (
            _version(updated_at=NOW - timedelta(minutes=30)),
            _hit(),
            60,
            "bundle_evidence_stale",
        ),
        (_version(), _hit(redaction_summary="content_redacted"), 3600, "document_redacted"),
        (
            _version(),
            _hit(conflicts="revision_conflict"),
            3600,
            "bundle_source_conflict",
        ),
    ],
)
async def test_stale_redacted_or_conflicting_evidence_holds_without_citations(
    version: DocumentVersion,
    hit: KnowledgeChunk,
    freshness: int,
    hold: str,
) -> None:
    gatherer = GovernedKnowledgeEvidenceGatherer(
        reader=_adapter(
            search=_Search((hit,)),
            metadata=_Metadata(version),
            access=_Access(),
            freshness_ceiling_seconds=freshness,
        )
    )

    result = await gatherer.gather(query="latency", context=_context())

    assert result.citations == ()
    assert hold in result.hold_reasons


async def test_missing_document_evidence_holds_without_citations() -> None:
    gatherer = GovernedKnowledgeEvidenceGatherer(
        reader=_adapter(
            search=_Search(()),
            metadata=_Metadata(None),
            access=_Access(),
        )
    )

    result = await gatherer.gather(query="latency", context=_context())

    assert result.citations == ()
    assert result.hold_reasons == ("document_evidence_missing",)


async def test_extra_document_manifest_entry_holds_without_citations() -> None:
    adapter = _adapter(
        search=_Search((_hit(),)),
        metadata=_Metadata(_version()),
        access=_Access(),
    )
    valid = await adapter.read(query="latency", context=_context(), limit=5)
    entry = valid.bundle.citation_manifest[0]
    forged_bundle = SimpleNamespace(
        **{
            field: getattr(valid.bundle, field)
            for field in (
                "bundle_id",
                "digest",
                "purpose",
                "scope",
                "cutoff",
                "ontology_release_digest",
                "catalog_revision",
                "claims",
                "ontology",
                "state",
                "catalog",
                "documents",
                "hold_required",
                "hold_reasons",
            )
        },
        citation_manifest=(
            entry,
            SimpleNamespace(
                evidence_ref="document:extra",
                lane=entry.lane,
                item_digest=entry.item_digest,
                source_revision=entry.source_revision,
                redaction_summary=entry.redaction_summary,
            ),
        ),
    )
    forged_result = SimpleNamespace(
        bundle=forged_bundle,
        principal_ref=valid.principal_ref,
        execution_authority=False,
        mutation_authority=False,
    )
    gatherer = GovernedKnowledgeEvidenceGatherer(
        reader=cast(GovernedDocumentEvidenceReader, _StaticReader(forged_result)),
    )

    result = await gatherer.gather(query="latency", context=_context())

    assert result.citations == ()
    assert result.hold_reasons == ("citation_manifest_mismatch",)


async def test_adapter_holds_when_document_was_deleted_after_search() -> None:
    adapter = _adapter(
        search=_Search((_hit(),)),
        metadata=_Metadata(_version(state=DocumentState.DELETED, available=False, active=False)),
        access=_Access(),
    )

    with pytest.raises(GovernedKnowledgeEvidenceHoldError, match="document_deleted_or_revoked"):
        await adapter.read(query="latency", context=_context(), limit=5)


async def test_adapter_holds_when_access_was_revoked_after_search() -> None:
    adapter = _adapter(
        search=_Search((_hit(),)),
        metadata=_Metadata(_version()),
        access=_Access(denied=True),
    )

    with pytest.raises(GovernedKnowledgeEvidenceHoldError, match="document_unauthorized"):
        await adapter.read(query="latency", context=_context(), limit=5)


async def test_adapter_holds_on_expected_revision_mismatch() -> None:
    context = _context(
        expected_revisions=(
            GovernedDocumentRevision(
                document_id=DOCUMENT_ID,
                version_id=OTHER_VERSION_ID,
                source_sha256=SOURCE_SHA,
            ),
        )
    )
    adapter = _adapter(
        search=_Search((_hit(),)),
        metadata=_Metadata(_version()),
        access=_Access(),
    )

    with pytest.raises(GovernedKnowledgeEvidenceHoldError, match="document_revision_mismatch"):
        await adapter.read(query="latency", context=context, limit=5)


class _CitingReasoner:
    async def reason(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RootCauseHypothesis:
        del incident_summary
        knowledge = tuple(
            citation for citation in candidate_citations if citation.kind is CitationKind.KNOWLEDGE
        )
        return RootCauseHypothesis(
            tier=RcaTier.T2,
            cause="dependency saturation",
            confidence=0.9,
            citations=knowledge,
        )


class _StaticReader:
    def __init__(self, result: object) -> None:
        self._result = result

    async def read(self, **_kwargs: object) -> object:
        return self._result


class _UnscopedSource:
    def __init__(self) -> None:
        self.called = False

    async def ingest(self, documents: Sequence[object]) -> int:
        del documents
        return 0

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:
        del query, k
        self.called = True
        raise AssertionError("governed evidence MUST NOT fall back to unscoped search")


async def test_coordinator_uses_governed_path_without_unscoped_fallback() -> None:
    unscoped = _UnscopedSource()
    governed = GovernedKnowledgeEvidenceGatherer(
        reader=_adapter(
            search=_Search((_hit(),)),
            metadata=_Metadata(_version()),
            access=_Access(),
        )
    )
    coordinator = RcaCoordinator(
        reasoner=_CitingReasoner(),
        knowledge_gatherer=KnowledgeEvidenceGatherer(source=unscoped),
        governed_knowledge_gatherer=governed,
    )

    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="dependency saturation",
        resource_ref="resource:example",
        since=NOW - timedelta(minutes=5),
        until=NOW,
        governed_knowledge_context=_context(),
    )

    assert coordinator.has_governed_knowledge is True
    assert result.is_grounded
    assert result.hypothesis is not None
    assert all(citation.kind is CitationKind.KNOWLEDGE for citation in result.hypothesis.citations)
    assert unscoped.called is False


async def test_coordinator_holds_unauthorized_governed_request_even_with_other_evidence() -> None:
    governed = GovernedKnowledgeEvidenceGatherer(
        reader=_adapter(
            search=_Search((_hit(),)),
            metadata=_Metadata(_version()),
            access=_Access(denied=True),
        )
    )
    coordinator = RcaCoordinator(
        reasoner=_CitingReasoner(),
        governed_knowledge_gatherer=governed,
    )

    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="dependency saturation",
        resource_ref="resource:example",
        since=NOW - timedelta(minutes=5),
        until=NOW,
        extra_citations=(Citation(CitationKind.EVENT, "event:example"),),
        governed_knowledge_context=_context(),
    )

    assert result.is_grounded is False
    assert result.hypothesis is None
    assert result.reason == "governed_knowledge_evidence_held:document_unauthorized"


async def test_missing_governed_binding_holds_without_unscoped_fallback() -> None:
    unscoped = _UnscopedSource()
    coordinator = RcaCoordinator(
        reasoner=_CitingReasoner(),
        knowledge_gatherer=KnowledgeEvidenceGatherer(source=unscoped),
    )

    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="dependency saturation",
        resource_ref="resource:example",
        since=NOW,
        until=NOW,
        governed_knowledge_context=_context(),
    )

    assert result.reason == "governed_knowledge_evidence_held:gatherer_unavailable"
    assert unscoped.called is False


class _EmptyGovernedGatherer:
    async def gather(self, **_kwargs: object) -> GovernedKnowledgeEvidenceResult:
        return GovernedKnowledgeEvidenceResult()


async def test_empty_custom_governed_result_holds_instead_of_using_other_evidence() -> None:
    coordinator = RcaCoordinator(
        reasoner=_CitingReasoner(),
        governed_knowledge_gatherer=cast(
            GovernedKnowledgeEvidenceGatherer,
            _EmptyGovernedGatherer(),
        ),
    )

    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="dependency saturation",
        resource_ref="resource:example",
        since=NOW,
        until=NOW,
        extra_citations=(Citation(CitationKind.EVENT, "event:example"),),
        governed_knowledge_context=_context(),
    )

    assert result.reason == "governed_knowledge_evidence_held:document_evidence_missing"
    assert result.hypothesis is None
