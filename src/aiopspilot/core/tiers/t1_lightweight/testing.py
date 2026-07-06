"""In-memory fakes for the T1 seams (tests + local dev)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from aiopspilot.core.tiers.t1_lightweight.tier import (
    EmbeddingModel,
    LearnedAction,
    PatternLibrary,
    SimilarityMatch,
    cosine_similarity,
)
from aiopspilot.shared.providers.pattern_library_writer import PatternLibraryWriter


class DeterministicEmbeddingModel(EmbeddingModel):
    """Hash-based fake embedding — same input → same vector, no network."""

    def __init__(self, *, dim: int = 32) -> None:
        self.dim = dim

    async def embed(self, text: str) -> Sequence[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Fold the digest into `dim` floats in [-1.0, 1.0]. Byte-level
        # noise gives similar-but-not-identical vectors to similar text.
        step = max(1, len(digest) // self.dim)
        vector: list[float] = []
        for i in range(self.dim):
            offset = (i * step) % len(digest)
            byte = digest[offset]
            vector.append((byte - 128) / 128.0)
        return vector


class InMemoryPatternLibrary(PatternLibrary, PatternLibraryWriter):
    """Dict-backed pattern library — brute-force cosine over stored actions."""

    def __init__(self) -> None:
        self._entries: list[tuple[Sequence[float], LearnedAction]] = []

    def add(self, *, vector: Sequence[float], action: LearnedAction) -> None:
        self._entries.append((vector, action))

    async def upsert_pattern(
        self,
        *,
        vector: Sequence[float],
        action: LearnedAction,
    ) -> None:
        """Async upsert keyed by :attr:`LearnedAction.signature`.

        Mirrors the semantics of the production pgvector adapter's
        ``ON CONFLICT (signature) DO UPDATE`` clause so tests exercise
        the same replay-safe contract the growth intake runner relies on.
        """
        for idx, (_, existing) in enumerate(self._entries):
            if existing.signature == action.signature:
                self._entries[idx] = (list(vector), action)
                return
        self._entries.append((list(vector), action))

    async def search(
        self, query_vector: Sequence[float], *, k: int = 5
    ) -> tuple[SimilarityMatch, ...]:
        scored = [
            SimilarityMatch(action=a, score=cosine_similarity(query_vector, v))
            for v, a in self._entries
        ]
        scored.sort(key=lambda m: m.score, reverse=True)
        return tuple(scored[:k])

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["DeterministicEmbeddingModel", "InMemoryPatternLibrary"]
