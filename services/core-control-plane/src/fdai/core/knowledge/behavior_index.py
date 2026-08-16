"""In-memory behavior knowledge index and tracked-source freshness validation.

The index answers "how does FDAI behave?" from structured `BehaviorSpec`
contracts. It never stores or returns source bodies: source evidence is
citation metadata used only to check freshness and authority, and retrieval
grants no approval or execution authority.

Ordering mirrors the PostgreSQL adapter contract: exact question aliases rank
first, exact identifier and normalized subject-token overlap rank next, then
fused lexical and semantic candidates. Implemented, test-backed records outrank
designed-only records inside the same match class and `behavior_id` breaks ties.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from fdai.shared.providers.behavior_knowledge import (
    BehaviorFreshness,
    BehaviorSearchResult,
    BehaviorSource,
    BehaviorSpec,
)
from fdai.shared.providers.knowledge import Embedder

RETRIEVAL_FLOOR = 0.05
RRF_K = 60
_MAX_RESULTS = 20
_WORD = re.compile(r"[a-z0-9]+")
_HANGUL = re.compile(r"[가-힣]+")
_STATUS_RANK = {"implemented": 0, "configured": 1, "designed": 2, "not_applicable": 3}


def normalize_tokens(text: str) -> tuple[str, ...]:
    """Return normalized retrieval tokens for Latin and Korean text."""

    lowered = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    for word in _WORD.findall(lowered.replace("_", " ").replace("-", " ").replace(".", " ")):
        tokens.append(_singular(word))
    for run in _HANGUL.findall(lowered):
        tokens.append(run)
        for start in range(len(run) - 1):
            tokens.append(run[start : start + 2])
    return tuple(tokens)


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


@dataclass(frozen=True, slots=True)
class TrackedSourceFreshnessValidator:
    """Validate citations against tracked repository blob hashes.

    The allowlist is built from tracked paths only, so ignored files, generated
    artifacts, local environment files, secrets, state files, and untracked
    files can never become source evidence.
    """

    tracked_blobs: Mapping[str, str]

    async def validate(self, source: BehaviorSource) -> BehaviorFreshness:
        current = self.tracked_blobs.get(source.path)
        if current is None:
            return BehaviorFreshness(fresh=False, tracked=False, current_blob_sha=None)
        return BehaviorFreshness(
            fresh=current == source.blob_sha,
            tracked=True,
            current_blob_sha=current,
        )


class InMemoryBehaviorKnowledgeIndex:
    """Deterministic reference index mirroring the persistent adapter ordering."""

    def __init__(
        self,
        validator: TrackedSourceFreshnessValidator,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self._validator = validator
        self._embedder = embedder
        self._specs: dict[str, BehaviorSpec] = {}

    async def upsert(self, spec: BehaviorSpec) -> bool:
        """Store `spec` idempotently and report whether the stored value changed."""

        previous = self._specs.get(spec.behavior_id)
        self._specs[spec.behavior_id] = spec
        return previous != spec

    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResult]:
        if k < 1 or k > _MAX_RESULTS:
            raise ValueError(f"behavior search k MUST be in [1, {_MAX_RESULTS}]")
        if not self._specs:
            return ()
        query_tokens = set(normalize_tokens(query))
        query_embedding = await self._embed(query)
        overlaps = self._lexical_overlaps(query_tokens)
        similarities = self._semantic_similarities(query_embedding)
        lexical = _ranks(overlaps)
        semantic = _ranks(similarities)
        scored: list[tuple[tuple[int, int, float, str], BehaviorSpec, str, float]] = []
        for behavior_id, spec in self._specs.items():
            match_kind, class_rank = self._classify(spec, query, query_tokens)
            relevance = max(overlaps.get(behavior_id, 0.0), similarities.get(behavior_id, 0.0))
            if match_kind == "hybrid" and relevance < RETRIEVAL_FLOOR:
                continue
            fused = _fuse(lexical.get(behavior_id), semantic.get(behavior_id))
            score = round(fused + (1.0 if class_rank == 0 else 0.5 if class_rank == 1 else 0.0), 6)
            authority = _authority_rank(spec)
            scored.append(((class_rank, authority, -score, behavior_id), spec, match_kind, score))
        scored.sort(key=lambda entry: entry[0])
        results: list[BehaviorSearchResult] = []
        for _, spec, match_kind, score in scored[:k]:
            stale_sources = await self._stale_sources(spec)
            results.append(
                BehaviorSearchResult(
                    spec=spec,
                    score=score,
                    match_kind=match_kind,  # type: ignore[arg-type]
                    stale=bool(stale_sources),
                    stale_sources=stale_sources,
                )
            )
        return tuple(results)

    async def compare(self, query: str, *, k: int = 2) -> Sequence[BehaviorSearchResult]:
        """Return only the fresh contracts a comparison question needs.

        Stale contracts are withheld rather than confirmed, so this method can
        return fewer than `k` results. The caller MUST treat fewer than two
        returned contracts as an incomplete comparison and abstain instead of
        presenting a one-sided answer as a verified comparison.
        """

        if k < 2:
            raise ValueError("behavior comparison MUST request at least two contracts")
        results = await self.search(query, k=k)
        return tuple(result for result in results if not result.stale)

    async def _stale_sources(self, spec: BehaviorSpec) -> tuple[BehaviorSource, ...]:
        stale: list[BehaviorSource] = []
        for source in spec.sources:
            freshness = await self._validator.validate(source)
            if not freshness.fresh or not freshness.tracked:
                stale.append(source)
        return tuple(stale)

    def _classify(
        self,
        spec: BehaviorSpec,
        query: str,
        query_tokens: set[str],
    ) -> tuple[str, int]:
        normalized_query = " ".join(normalize_tokens(query))
        for alias in spec.question_aliases:
            if " ".join(normalize_tokens(alias)) == normalized_query:
                return "exact_alias", 0
        identifiers = {
            *normalize_tokens(spec.behavior_id),
            *normalize_tokens(spec.subject_id),
        }
        if identifiers & query_tokens:
            return "exact_identifier", 1
        return "hybrid", 2

    def _lexical_overlaps(self, query_tokens: set[str]) -> dict[str, float]:
        overlaps: dict[str, float] = {}
        if not query_tokens:
            return overlaps
        for behavior_id, spec in self._specs.items():
            tokens = set(normalize_tokens(spec.search_text()))
            overlap = len(tokens & query_tokens) / len(query_tokens)
            if overlap > 0:
                overlaps[behavior_id] = overlap
        return overlaps

    def _semantic_similarities(
        self,
        query_embedding: tuple[float, ...] | None,
    ) -> dict[str, float]:
        if query_embedding is None:
            return {}
        similarities: dict[str, float] = {}
        for behavior_id, spec in self._specs.items():
            if not spec.embedding:
                continue
            similarity = _cosine(query_embedding, spec.embedding)
            if similarity > 0:
                similarities[behavior_id] = similarity
        return similarities

    async def _embed(self, query: str) -> tuple[float, ...] | None:
        if self._embedder is None:
            return None
        return tuple(float(value) for value in await self._embedder.embed(query))


def _authority_rank(spec: BehaviorSpec) -> int:
    """Rank implemented, test-backed contracts above designed-only contracts."""

    status_rank = _STATUS_RANK.get(spec.status, len(_STATUS_RANK))
    return status_rank * 2 + (0 if spec.test_backed else 1)


def _ranks(scores: Mapping[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda entry: (-entry[1], entry[0]))
    return {behavior_id: rank for rank, (behavior_id, _) in enumerate(ordered, start=1)}


def _fuse(lexical_rank: int | None, semantic_rank: int | None) -> float:
    score = 0.0
    for rank in (lexical_rank, semantic_rank):
        if rank is not None:
            score += 1.0 / (RRF_K + rank)
    return round(score, 6)


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = tuple(left)
    right_values = tuple(right)
    if len(left_values) != len(right_values):
        return 0.0
    dot = sum(a * b for a, b in zip(left_values, right_values, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


__all__ = [
    "RETRIEVAL_FLOOR",
    "InMemoryBehaviorKnowledgeIndex",
    "TrackedSourceFreshnessValidator",
    "normalize_tokens",
]
