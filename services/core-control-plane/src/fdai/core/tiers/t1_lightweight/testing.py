"""In-memory fakes for the T1 seams (tests + local dev)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace

from fdai.core.tiers.t1_lightweight.tier import (
    EmbeddingModel,
    LearnedAction,
    PatternLibrary,
    SimilarityMatch,
    cosine_similarity,
)
from fdai.shared.providers.pattern_library_writer import PatternLibraryWriter


class DeterministicEmbeddingModel(EmbeddingModel):
    """Hash-based fake embedding - same input → same vector, no network."""

    def __init__(self, *, dim: int = 384) -> None:
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
    """Dict-backed pattern library - brute-force cosine over stored actions."""

    def __init__(self) -> None:
        self._entries: list[tuple[Sequence[float], LearnedAction]] = []

    def add(self, *, vector: Sequence[float], action: LearnedAction) -> None:
        self._entries.append((vector, action))

    def signatures(self) -> tuple[str, ...]:
        """Return stored pattern signatures in insertion order."""
        return tuple(action.signature for _vec, action in self._entries)

    def seed_patterns(
        self,
        entries: Sequence[tuple[Sequence[float], LearnedAction]],
    ) -> int:
        """Seed baseline patterns idempotently by signature and return newly added count."""
        known = {action.signature for _vec, action in self._entries}
        added = 0
        for vector, action in entries:
            if action.signature in known:
                continue
            self._entries.append((list(vector), action))
            known.add(action.signature)
            added += 1
        return added

    def remove_pattern(self, signature: str) -> bool:
        """Remove a stored pattern by signature and return whether an entry was removed."""
        for idx, (_vec, existing) in enumerate(self._entries):
            if existing.signature == signature:
                del self._entries[idx]
                return True
        return False

    def clear(self) -> None:
        """Remove all stored patterns."""
        self._entries.clear()

    def find_by_rule_id(self, rule_id: str) -> tuple[LearnedAction, ...]:
        """Return all stored actions citing ``rule_id``."""
        return tuple(action for _vec, action in self._entries if action.rule_id == rule_id)

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
                if action.operational_case is None and existing.operational_case is not None:
                    action = replace(action, operational_case=existing.operational_case)
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
