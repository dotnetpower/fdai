"""Tests for the knowledge-base RAG seam."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from fdai.shared.providers.knowledge import (
    EmbeddingKnowledgeSource,
    EmptyKnowledgeSource,
    KnowledgeDocument,
    chunk_text,
    cosine_similarity,
)


class _KeywordEmbedder:
    """Deterministic bag-of-words embedder over a fixed vocabulary.

    Network-free and reproducible: each text maps to a term-frequency
    vector over the vocabulary, so cosine similarity reflects keyword
    overlap. Enough to assert retrieval ranking without a real model.
    """

    _VOCAB = ("disk", "full", "cpu", "throttle", "network", "latency", "restart", "pod")

    async def embed(self, text: str) -> Sequence[float]:
        words = text.lower().split()
        return [float(words.count(term)) for term in self._VOCAB]


def test_chunk_text_small_document_single_chunk() -> None:
    assert chunk_text("short text") == ["short text"]
    assert chunk_text("   ") == []


def test_chunk_text_splits_with_overlap() -> None:
    body = "\n\n".join(f"paragraph {i} about disks and cpu" for i in range(20))
    chunks = chunk_text(body, max_chars=120, overlap=30)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_chunk_text_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("x", max_chars=10, overlap=10)


def test_cosine_similarity_edges() -> None:
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_empty_source_returns_nothing() -> None:
    src = EmptyKnowledgeSource()
    assert await src.ingest([]) == 0
    assert await src.search("disk full", k=3) == ()


@pytest.mark.asyncio
async def test_ingest_and_search_ranks_by_relevance() -> None:
    src = EmbeddingKnowledgeSource(embedder=_KeywordEmbedder())
    docs = [
        KnowledgeDocument(doc_id="d1", source_ref="wiki/disk", text="disk full disk full"),
        KnowledgeDocument(doc_id="d2", source_ref="wiki/cpu", text="cpu throttle cpu throttle"),
        KnowledgeDocument(
            doc_id="d3", source_ref="wiki/net", text="network latency network latency"
        ),
    ]
    added = await src.ingest(docs)
    assert added == 3

    results = await src.search("disk full", k=2)
    assert len(results) == 2
    assert results[0].doc_id == "d1"  # most relevant first
    assert results[0].source_ref == "wiki/disk"  # citation preserved
    assert results[0].score > results[1].score


@pytest.mark.asyncio
async def test_search_empty_index_returns_empty() -> None:
    src = EmbeddingKnowledgeSource(embedder=_KeywordEmbedder())
    assert await src.search("anything", k=5) == ()


@pytest.mark.asyncio
async def test_search_respects_k_and_zero_k() -> None:
    src = EmbeddingKnowledgeSource(embedder=_KeywordEmbedder())
    await src.ingest(
        [KnowledgeDocument(doc_id=f"d{i}", source_ref=f"s{i}", text="disk full") for i in range(5)]
    )
    assert len(await src.search("disk", k=3)) == 3
    assert await src.search("disk", k=0) == ()
