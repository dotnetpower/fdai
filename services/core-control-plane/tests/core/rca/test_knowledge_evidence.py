"""Tests for the free-form knowledge RCA evidence leg."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    EvidenceLane,
    OperationalEvidenceReadRequest,
)
from fdai.core.rca.contract import Citation, CitationKind, RcaTier, RootCauseHypothesis
from fdai.core.rca.coordinator import RcaCoordinator
from fdai.core.rca.governed_knowledge_evidence import (
    GovernedDocumentAccessContext,
    GovernedDocumentEvidenceReader,
    GovernedDocumentRevision,
    GovernedKnowledgeBindings,
    GovernedKnowledgeEvidenceContext,
    GovernedKnowledgeEvidenceContextProvider,
    GovernedKnowledgeEvidenceGatherer,
    GovernedKnowledgeEvidenceHoldError,
    GovernedKnowledgeEvidenceResult,
    governed_access_binding,
    governed_evidence_digest,
)
from fdai.core.rca.knowledge_evidence import KnowledgeEvidenceGatherer
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.knowledge import KnowledgeChunk


class _StubSource:
    """Minimal KnowledgeSource returning canned chunks."""

    def __init__(self, chunks: Sequence[KnowledgeChunk], *, raises: bool = False) -> None:
        self._chunks = tuple(chunks)
        self._raises = raises
        self.last_k: int | None = None

    async def ingest(self, documents: Sequence[object]) -> int:  # noqa: ARG002 - unused
        return 0

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:  # noqa: ARG002
        if self._raises:
            raise RuntimeError("backend down")
        self.last_k = k
        return self._chunks[:k]


def _chunk(doc_id: str, i: int, *, source_ref: str, score: float) -> KnowledgeChunk:
    return KnowledgeChunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#{i}",
        text="body text",
        source_ref=source_ref,
        score=score,
    )


@pytest.mark.asyncio
async def test_unbound_source_yields_no_citations() -> None:
    gatherer = KnowledgeEvidenceGatherer(source=None)
    assert gatherer.is_bound is False
    assert await gatherer.gather(query="disk full") == ()


@pytest.mark.asyncio
async def test_empty_query_yields_nothing() -> None:
    src = _StubSource([_chunk("d1", 0, source_ref="wiki/disk", score=0.9)])
    gatherer = KnowledgeEvidenceGatherer(source=src)
    assert await gatherer.gather(query="   ") == ()


@pytest.mark.asyncio
async def test_maps_chunks_to_knowledge_citations() -> None:
    src = _StubSource(
        [
            _chunk("d1", 0, source_ref="wiki/disk", score=0.9),
            _chunk("d1", 1, source_ref="wiki/disk", score=0.7),
        ]
    )
    gatherer = KnowledgeEvidenceGatherer(source=src)
    cites = await gatherer.gather(query="disk full")
    assert [c.kind for c in cites] == [CitationKind.KNOWLEDGE, CitationKind.KNOWLEDGE]
    assert cites[0].ref == "knowledge:wiki/disk#d1#0"
    assert cites[1].ref == "knowledge:wiki/disk#d1#1"


@pytest.mark.asyncio
async def test_min_score_filters_low_relevance() -> None:
    src = _StubSource(
        [
            _chunk("d1", 0, source_ref="wiki/a", score=0.9),
            _chunk("d2", 0, source_ref="wiki/b", score=0.2),
        ]
    )
    gatherer = KnowledgeEvidenceGatherer(source=src, min_score=0.5)
    cites = await gatherer.gather(query="q")
    assert [c.ref for c in cites] == ["knowledge:wiki/a#d1#0"]


@pytest.mark.asyncio
async def test_deduplicates_by_ref() -> None:
    dup = _chunk("d1", 0, source_ref="wiki/a", score=0.9)
    src = _StubSource([dup, dup])
    gatherer = KnowledgeEvidenceGatherer(source=src)
    cites = await gatherer.gather(query="q")
    assert len(cites) == 1


@pytest.mark.asyncio
async def test_source_outage_fails_closed() -> None:
    src = _StubSource([], raises=True)
    gatherer = KnowledgeEvidenceGatherer(source=src)
    assert await gatherer.gather(query="q") == ()


@pytest.mark.asyncio
async def test_limit_caps_top_k() -> None:
    chunks = [_chunk("d", i, source_ref="wiki/a", score=0.9) for i in range(5)]
    src = _StubSource(chunks)
    gatherer = KnowledgeEvidenceGatherer(source=src, top_k=5)
    await gatherer.gather(query="q", limit=2)
    assert src.last_k == 2


def test_invalid_construction_rejected() -> None:
    with pytest.raises(ValueError):
        KnowledgeEvidenceGatherer(top_k=0)
    with pytest.raises(ValueError):
        KnowledgeEvidenceGatherer(min_score=1.5)


class _KnowledgeCitingReasoner:
    """Reasoner that cites every KNOWLEDGE citation it was handed."""

    async def reason(
        self, *, incident_summary: str, candidate_citations: Sequence[object]
    ) -> RootCauseHypothesis:
        del incident_summary
        knowledge = tuple(
            c for c in candidate_citations if getattr(c, "kind", None) == CitationKind.KNOWLEDGE
        )
        return RootCauseHypothesis(
            tier=RcaTier.T2,
            cause="resource plan mismatch",
            confidence=0.9,
            citations=knowledge,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_coordinator_grounds_t2_on_uploaded_document() -> None:
    src = _StubSource([_chunk("plan", 0, source_ref="plan/db", score=0.95)])
    coordinator = RcaCoordinator(
        reasoner=_KnowledgeCitingReasoner(),
        knowledge_gatherer=KnowledgeEvidenceGatherer(source=src),
    )
    assert coordinator.has_knowledge is True

    now = datetime(2026, 7, 13, tzinfo=UTC)
    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="database latency spike",
        resource_ref="rg/db/primary",
        since=now,
        until=now,
    )
    assert result.is_grounded
    assert result.hypothesis is not None
    assert any(c.kind == CitationKind.KNOWLEDGE for c in result.hypothesis.citations)


@pytest.mark.asyncio
async def test_coordinator_without_knowledge_is_backward_compatible() -> None:
    coordinator = RcaCoordinator(reasoner=_KnowledgeCitingReasoner())
    assert coordinator.has_knowledge is False
    now = datetime(2026, 7, 13, tzinfo=UTC)
    # No knowledge, no telemetry -> empty candidate set -> abstains.
    result = await coordinator.analyze_t2_from_telemetry(
        incident_summary="database latency spike",
        resource_ref="rg/db/primary",
        since=now,
        until=now,
    )
    assert result.is_grounded is False


@pytest.mark.asyncio
async def test_knowledge_gatherer_skips_low_score_then_fills_and_dedupes() -> None:
    src = _StubSource(
        [
            _chunk("low", 0, source_ref="wiki/low", score=0.10),
            _chunk("dup", 1, source_ref="wiki/dup", score=0.90),
            _chunk("dup", 1, source_ref="wiki/dup", score=0.88),
            _chunk("second", 0, source_ref="wiki/second", score=0.85),
        ]
    )
    gatherer = KnowledgeEvidenceGatherer(source=src, top_k=4, min_score=0.5)
    got = await gatherer.gather(query="latency spike")
    assert [c.ref for c in got] == ["knowledge:wiki/dup#dup#1", "knowledge:wiki/second#second#0"]


_GOV_NOW = datetime(2026, 9, 4, 2, 30, tzinfo=UTC)
_GOV_RELEASE = "sha256:" + "b" * 64
_GOV_SCOPE = "sha256:" + "c" * 64


def _gov_context() -> GovernedKnowledgeEvidenceContext:
    authority = SecuredQueryReceiptAuthority(now=lambda: _GOV_NOW)
    principal = AuthenticatedPrincipalContext(
        principal_ref="principal:responder",
        principal_scope_digest=_GOV_SCOPE,
        purpose="incident-review",
        receipt_authority=authority,
        invocation_context=FunctionInvocationContext(
            caller_agent="Forseti",
            caller_role=CeilingRole.READER,
            purposes=("incident-review",),
        ),
        verification_context=authority.verification_context,
    )
    return GovernedKnowledgeEvidenceContext(
        read_request=OperationalEvidenceReadRequest(
            ontology_release_digest=_GOV_RELEASE,
            catalog_revision="catalog-r1",
            purpose="incident-review",
            scope=("resource:example",),
            cutoff=_GOV_NOW,
        ),
        authenticated_context=principal,
        access_context=GovernedDocumentAccessContext(
            collection_id="operations",
            access_context_ref="access-context:incident-review",
            allowed_access_refs=frozenset({"collection:operations"}),
            actor_groups=frozenset({"group:responders"}),
        ),
        expected_revisions=(GovernedDocumentRevision(UUID(int=1), UUID(int=2), "a" * 64),),
    )


def _gov_read_result(context: GovernedKnowledgeEvidenceContext) -> SimpleNamespace:
    access_map = {**governed_access_binding(context), "document_revision": "rev-1"}

    class _Source:
        document_revision: str | None = "rev-1"
        source_revision: str = "rev-1"

        def membership_evidence_mapping(self) -> dict[str, object]:
            return dict(access_map)

    doc = SimpleNamespace(evidence_ref="doc:1", source=_Source())
    entry = SimpleNamespace(
        evidence_ref="doc:1",
        lane=EvidenceLane.DOCUMENT,
        item_digest="sha256:" + "d" * 64,
        source_revision="rev-1",
        redaction_summary=("none",),
    )
    bundle = SimpleNamespace(
        bundle_id="bundle-1",
        digest="sha256:" + "e" * 64,
        purpose="incident-review",
        scope=("resource:example",),
        cutoff=_GOV_NOW,
        ontology_release_digest=_GOV_RELEASE,
        catalog_revision="catalog-r1",
        claims=(),
        ontology=(),
        state=(),
        catalog=(),
        documents=(doc,),
        citation_manifest=(entry,),
        hold_required=False,
        hold_reasons=(),
    )
    return SimpleNamespace(
        bundle=bundle,
        principal_ref="principal:responder",
        execution_authority=False,
        mutation_authority=False,
    )


def test_governed_knowledge_models_and_digest_validations() -> None:
    ctx = _gov_context()
    assert governed_evidence_digest("raw").startswith("sha256:")
    assert governed_evidence_digest({"a": 1}).startswith("sha256:")

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        GovernedDocumentRevision(UUID(int=1), UUID(int=2), "BAD")
    with pytest.raises(ValueError, match="collection and access context"):
        GovernedDocumentAccessContext("", "ref", frozenset({"a"}), frozenset())
    with pytest.raises(ValueError, match="allowed access refs"):
        GovernedDocumentAccessContext("col", "ref", frozenset({" "}), frozenset())
    with pytest.raises(ValueError, match="actor groups"):
        GovernedDocumentAccessContext("col", "ref", frozenset({"a"}), frozenset({" "}))
    with pytest.raises(ValueError, match="purpose does not match"):
        replace(ctx, read_request=replace(ctx.read_request, purpose="other"))
    dup_rev = GovernedDocumentRevision(UUID(int=1), UUID(int=3), "b" * 64)
    with pytest.raises(ValueError, match="unique document ids"):
        replace(ctx, expected_revisions=(*ctx.expected_revisions, dup_rev))

    cite = Citation(CitationKind.KNOWLEDGE, "knowledge:1")
    with pytest.raises(ValueError, match="cannot cite while held"):
        GovernedKnowledgeEvidenceResult(citations=(cite,), hold_reasons=("held",))
    with pytest.raises(ValueError, match="only KNOWLEDGE citations"):
        GovernedKnowledgeEvidenceResult(citations=(Citation(CitationKind.EVENT, "ev:1"),))
    with pytest.raises(ValueError, match="bundle_id MUST be non-empty"):
        GovernedKnowledgeEvidenceResult(bundle_id="  ")
    assert GovernedKnowledgeEvidenceResult(hold_reasons=("h",)).hold_required is True
    assert GovernedKnowledgeEvidenceResult(citations=(cite,)).hold_required is False

    for bad_k in (True, 0, 21):
        with pytest.raises(ValueError, match="top_k MUST be in"):
            GovernedKnowledgeEvidenceGatherer(
                reader=cast(GovernedDocumentEvidenceReader, object()),
                top_k=bad_k,
            )


@pytest.mark.asyncio
async def test_governed_knowledge_gatherer_and_citation_verification_branches() -> None:
    ctx = _gov_context()

    class _Reader:
        def __init__(self, outcome: object) -> None:
            self.outcome = outcome

        async def read(self, **_kwargs: object) -> object:
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    valid_res = _gov_read_result(ctx)
    gatherer = GovernedKnowledgeEvidenceGatherer(
        reader=cast(GovernedDocumentEvidenceReader, _Reader(valid_res)),
        top_k=5,
    )
    bindings = GovernedKnowledgeBindings(
        gatherer=gatherer,
        context_provider=cast(GovernedKnowledgeEvidenceContextProvider, object()),
    )
    assert bindings.gatherer is gatherer

    invalid_limit = await gatherer.gather(query="q", context=ctx, limit=True)
    assert invalid_limit.hold_reasons == ("invalid_limit",)

    ok = await gatherer.gather(query="q", context=ctx, limit=2)
    assert len(ok.citations) == 1
    assert ok.bundle_id == "bundle-1"

    held_err = await GovernedKnowledgeEvidenceGatherer(
        reader=cast(
            GovernedDocumentEvidenceReader,
            _Reader(GovernedKnowledgeEvidenceHoldError("custom_hold")),
        )
    ).gather(query="q", context=ctx)
    assert held_err.hold_reasons == ("custom_hold",)

    boom = await GovernedKnowledgeEvidenceGatherer(
        reader=cast(GovernedDocumentEvidenceReader, _Reader(RuntimeError("down")))
    ).gather(query="q", context=ctx)
    assert boom.hold_reasons == ("provider_unavailable",)

    def _clone(
        *,
        result_updates: dict[str, object] | None = None,
        bundle_updates: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        base = _gov_read_result(ctx)
        if bundle_updates:
            for k, v in bundle_updates.items():
                setattr(base.bundle, k, v)
        if result_updates:
            for k, v in result_updates.items():
                setattr(base, k, v)
        return base

    class _FlippingRefDoc:
        def __init__(self, source: object) -> None:
            self.source = source
            self._calls = 0

        @property
        def evidence_ref(self) -> str:
            self._calls += 1
            return "doc:1" if self._calls == 1 else "doc:missing"

    base_source = _gov_read_result(ctx).bundle.documents[0].source

    class _BadRevSource:
        document_revision = None
        source_revision = "rev-1"

    class _BadAccessSource:
        document_revision = "rev-1"
        source_revision = "rev-1"

        def membership_evidence_mapping(self) -> dict[str, object]:
            return {"principal_ref": "other"}

    class _BadMemberRevSource:
        document_revision = "rev-1"
        source_revision = "rev-1"

        def membership_evidence_mapping(self) -> dict[str, object]:
            return {**governed_access_binding(ctx), "document_revision": "other"}

    redacted_entry = SimpleNamespace(
        evidence_ref="doc:1",
        lane=EvidenceLane.DOCUMENT,
        item_digest="sha256:" + "d" * 64,
        source_revision="rev-1",
        redaction_summary=("pii",),
    )

    for forged, expected_hold in (
        (_clone(result_updates={"execution_authority": True}), "principal_or_authority_mismatch"),
        (_clone(bundle_updates={"purpose": "other"}), "bundle_identity_mismatch"),
        (_clone(bundle_updates={"claims": ("claim:1",)}), "unexpected_evidence_lane"),
        (
            _clone(bundle_updates={"hold_required": True, "hold_reasons": ("stale",)}),
            "bundle_stale",
        ),
        (_clone(bundle_updates={"documents": ()}), "document_evidence_missing"),
        (_clone(bundle_updates={"citation_manifest": ()}), "citation_manifest_mismatch"),
        (
            _clone(bundle_updates={"documents": (_FlippingRefDoc(base_source),)}),
            "citation_manifest_missing",
        ),
        (
            _clone(
                bundle_updates={
                    "documents": (SimpleNamespace(evidence_ref="doc:1", source=_BadRevSource()),)
                }
            ),
            "document_revision_mismatch",
        ),
        (
            _clone(bundle_updates={"citation_manifest": (redacted_entry,)}),
            "document_redacted",
        ),
        (
            _clone(
                bundle_updates={
                    "documents": (SimpleNamespace(evidence_ref="doc:1", source=_BadAccessSource()),)
                }
            ),
            "access_binding_mismatch",
        ),
        (
            _clone(
                bundle_updates={
                    "documents": (
                        SimpleNamespace(evidence_ref="doc:1", source=_BadMemberRevSource()),
                    )
                }
            ),
            "document_revision_mismatch",
        ),
    ):
        res = await GovernedKnowledgeEvidenceGatherer(
            reader=cast(GovernedDocumentEvidenceReader, _Reader(forged))
        ).gather(query="q", context=ctx)
        assert res.hold_reasons == (expected_hold,)
