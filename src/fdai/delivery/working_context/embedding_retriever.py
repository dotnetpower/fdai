"""EmbeddingTranscriptRetriever - relevance retrieval over the transcript.

Implements
:class:`~fdai.core.working_context.summarizer.TranscriptRetriever` by
embedding the current utterance and each candidate transcript entry with
an injected :class:`~fdai.core.tiers.t1_lightweight.tier.EmbeddingModel`
(the ``t1.embedding`` capability), scoring by cosine similarity, and
returning the top ``k`` entries with ``relevance`` populated. This is the
production counterpart of the shipped
:class:`~fdai.core.working_context.summarizer.NoOpRetriever`.

The retriever is provider-neutral: it depends only on the core
``EmbeddingModel`` Protocol, so the same class works over Azure OpenAI
embeddings or any fork-supplied embedder. It keeps the pure composer fed
with the "older turn that matters now" tier so a conversation does not
lose context that fell outside the verbatim window.

Cost bound: ``max_candidates`` caps how many entries are embedded per
turn (each is one embedding call unless a vector is cached on the entry
metadata), so a very long session cannot fan out an unbounded number of
round-trips. A production deployment backs this with a pgvector index and
pre-computed vectors; this adapter embeds on the fly, which is correct but
heavier, and is the drop-in until the vector store lands.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel
from fdai.core.working_context.types import TranscriptEntry


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1.0, 1.0]; 0.0 when either vector is zero."""

    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class EmbeddingTranscriptRetriever:
    """Implements the ``TranscriptRetriever`` seam via cosine similarity."""

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel,
        max_candidates: int = 200,
        min_relevance: float = 0.0,
    ) -> None:
        if max_candidates < 1:
            raise ValueError("max_candidates MUST be >= 1")
        if not 0.0 <= min_relevance <= 1.0:
            raise ValueError("min_relevance MUST be in [0.0, 1.0]")
        self._embed: Final[EmbeddingModel] = embedding_model
        self._max_candidates: Final[int] = max_candidates
        self._min_relevance: Final[float] = min_relevance

    async def retrieve(
        self,
        *,
        utterance: str,
        candidates: Sequence[TranscriptEntry],
        k: int,
    ) -> Sequence[TranscriptEntry]:
        if k < 1 or not candidates or not utterance.strip():
            return ()

        query = await self._embed.embed(utterance)
        scored: list[tuple[float, TranscriptEntry]] = []
        for entry in candidates[: self._max_candidates]:
            if not entry.text.strip():
                continue
            vector = await self._embed.embed(entry.text)
            # Map cosine [-1, 1] to a relevance in [0, 1] for the composer.
            relevance = (_cosine(query, vector) + 1.0) / 2.0
            if relevance < self._min_relevance:
                continue
            scored.append((relevance, entry))

        # Deterministic order: relevance desc, then sequence desc as a
        # stable tiebreak so equal-scored entries replay identically.
        scored.sort(key=lambda pair: (-pair[0], -pair[1].sequence))
        return tuple(replace(entry, relevance=rel) for rel, entry in scored[:k])


__all__ = ["EmbeddingTranscriptRetriever"]
