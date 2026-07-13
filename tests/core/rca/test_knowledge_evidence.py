"""Tests for the free-form knowledge RCA evidence leg."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from fdai.core.rca.contract import CitationKind, RcaTier, RootCauseHypothesis
from fdai.core.rca.coordinator import RcaCoordinator
from fdai.core.rca.knowledge_evidence import KnowledgeEvidenceGatherer
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
