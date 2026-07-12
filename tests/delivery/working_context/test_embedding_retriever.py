"""Tests for EmbeddingTranscriptRetriever (cosine over an injected embedder)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from fdai.core.working_context.types import EntryKind, EntryRole, TranscriptEntry
from fdai.delivery.working_context.embedding_retriever import (
    EmbeddingTranscriptRetriever,
)


class _KeywordEmbedder:
    """Deterministic fake: a 3-dim vector flagging vm / disk / network."""

    dim = 3

    async def embed(self, text: str) -> Sequence[float]:
        low = text.lower()
        return [
            1.0 if "vm" in low else 0.0,
            1.0 if "disk" in low else 0.0,
            1.0 if "network" in low else 0.0,
        ]


def _entry(entry_id: str, text: str, *, sequence: int) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=entry_id,
        role=EntryRole.OPERATOR,
        kind=EntryKind.RETRIEVED,
        text=text,
        tokens=10,
        sequence=sequence,
    )


def _retriever(**kw: object) -> EmbeddingTranscriptRetriever:
    return EmbeddingTranscriptRetriever(embedding_model=_KeywordEmbedder(), **kw)  # type: ignore[arg-type]


async def test_returns_most_relevant_first_with_relevance_set() -> None:
    candidates = [
        _entry("disk", "disk is full", sequence=1),
        _entry("vm", "the vm crashed", sequence=2),
        _entry("vmdisk", "vm disk pressure", sequence=3),
    ]
    got = await _retriever().retrieve(utterance="restart the vm", candidates=candidates, k=2)
    # query [1,0,0]: vm -> cosine 1.0 (rel 1.0); vmdisk [1,1,0] -> cosine
    # 1/sqrt(2) ~ 0.707 (rel ~0.85); disk [0,1,0] -> 0 (rel 0.5).
    assert [e.entry_id for e in got] == ["vm", "vmdisk"]
    assert got[0].relevance == pytest.approx(1.0)
    assert got[1].relevance == pytest.approx((1 / 2**0.5 + 1) / 2)


async def test_k_caps_results() -> None:
    candidates = [_entry(f"e{i}", "vm here", sequence=i) for i in range(5)]
    got = await _retriever().retrieve(utterance="vm", candidates=candidates, k=2)
    assert len(got) == 2


async def test_min_relevance_filters() -> None:
    candidates = [_entry("disk", "disk full", sequence=1)]
    # utterance "vm" vs "disk full" -> relevance 0.5; threshold 0.9 drops it.
    got = await _retriever(min_relevance=0.9).retrieve(utterance="vm", candidates=candidates, k=3)
    assert got == ()


async def test_empty_inputs_return_nothing() -> None:
    r = _retriever()
    assert await r.retrieve(utterance="", candidates=[_entry("a", "vm", sequence=1)], k=3) == ()
    assert await r.retrieve(utterance="vm", candidates=[], k=3) == ()
    assert await r.retrieve(utterance="vm", candidates=[_entry("a", "vm", sequence=1)], k=0) == ()


async def test_max_candidates_bounds_embedding_calls() -> None:
    candidates = [_entry(f"e{i}", "vm", sequence=i) for i in range(10)]
    got = await _retriever(max_candidates=3).retrieve(utterance="vm", candidates=candidates, k=10)
    # Only the first 3 candidates are considered.
    assert len(got) == 3


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="max_candidates"):
        _retriever(max_candidates=0)
    with pytest.raises(ValueError, match="min_relevance"):
        _retriever(min_relevance=1.5)
