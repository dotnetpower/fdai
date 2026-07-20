"""In-memory reference implementation of structured behavior retrieval."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from fdai.shared.providers.behavior_knowledge import (
    BehaviorKnowledgeIndex,
    BehaviorMatchKind,
    BehaviorSearchResult,
    BehaviorSource,
    BehaviorSourceValidator,
    BehaviorSpec,
    Embedder,
)
from fdai.shared.providers.knowledge import cosine_similarity

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")
_RRF_K = 60.0
_MIN_LEXICAL_SCORE = 0.25
_MIN_SEMANTIC_SCORE = 0.35
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "do",
        "does",
        "how",
        "is",
        "of",
        "or",
        "the",
        "to",
        "what",
        "when",
        "why",
        "가",
        "과",
        "는",
        "로",
        "를",
        "에서",
        "와",
        "은",
        "이",
        "의",
        "을",
    }
)


def _normalized_tokens(value: str) -> tuple[str, ...]:
    normalized = []
    for raw in _TOKEN.findall(value.casefold()):
        token = raw[:-1] if raw.endswith("s") and len(raw) > 4 else raw
        if token and token not in _STOP_WORDS:
            normalized.append(token)
    return tuple(normalized)


def _normalize(value: str) -> str:
    return " ".join(_normalized_tokens(value))


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_normalized_tokens(value))


class InMemoryBehaviorKnowledgeIndex(BehaviorKnowledgeIndex):
    """Hybrid exact, lexical, and semantic behavior index.

    Exact aliases and identifiers always outrank fused retrieval. Within a
    retrieval class, implemented test-backed contracts receive an authority
    boost. Freshness affects trust state, not rank, so callers can explicitly
    abstain instead of silently substituting a weaker contract.
    """

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        source_validator: BehaviorSourceValidator | None = None,
    ) -> None:
        self._embedder = embedder
        self._source_validator = source_validator
        self._specs: dict[str, BehaviorSpec] = {}

    async def upsert(self, spec: BehaviorSpec) -> bool:
        stored = spec
        if not spec.embedding and self._embedder is not None:
            stored = replace(spec, embedding=tuple(await self._embedder.embed(spec.search_text())))
        previous = self._specs.get(stored.behavior_id)
        if previous == stored:
            return False
        self._specs[stored.behavior_id] = stored
        return True

    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResult]:
        if k <= 0 or not query.strip() or not self._specs:
            return ()
        normalized_query = _normalize(query)
        query_tokens = _tokens(query)
        query_vector = (
            tuple(await self._embedder.embed(query)) if self._embedder is not None else ()
        )

        lexical = sorted(
            self._specs.values(),
            key=lambda spec: self._lexical_score(spec, query_tokens),
            reverse=True,
        )
        semantic = sorted(
            self._specs.values(),
            key=lambda spec: cosine_similarity(query_vector, spec.embedding),
            reverse=True,
        )
        lexical_rank = {spec.behavior_id: rank for rank, spec in enumerate(lexical, start=1)}
        semantic_rank = {spec.behavior_id: rank for rank, spec in enumerate(semantic, start=1)}

        ranked: list[tuple[tuple[float, ...], BehaviorSpec, BehaviorMatchKind]] = []
        for spec in self._specs.values():
            aliases = {_normalize(alias) for alias in spec.question_aliases}
            exact_alias = normalized_query in aliases
            exact_identifier = _normalize(spec.subject_id) in normalized_query
            subject_tokens = _tokens(spec.subject_id)
            subject_score = (
                len(query_tokens & subject_tokens) / len(subject_tokens) if subject_tokens else 0.0
            )
            lexical_score = self._lexical_score(spec, query_tokens)
            semantic_score = cosine_similarity(query_vector, spec.embedding)
            if (
                not exact_alias
                and not exact_identifier
                and (lexical_score < _MIN_LEXICAL_SCORE and semantic_score < _MIN_SEMANTIC_SCORE)
            ):
                continue
            if exact_alias:
                match_kind: BehaviorMatchKind = "exact_alias"
            elif exact_identifier:
                match_kind = "exact_identifier"
            else:
                match_kind = "hybrid"
            authority = float(spec.status == "implemented") + float(spec.test_backed)
            rrf = 1.0 / (_RRF_K + lexical_rank[spec.behavior_id])
            if query_vector and spec.embedding:
                rrf += 1.0 / (_RRF_K + semantic_rank[spec.behavior_id])
            ranking_key = (
                float(exact_alias),
                float(exact_identifier),
                subject_score,
                authority,
                rrf,
                lexical_score,
                semantic_score,
            )
            ranked.append((ranking_key, spec, match_kind))
        ranked.sort(key=lambda item: (*item[0], item[1].behavior_id), reverse=True)

        results = []
        for stored_key, spec, match_kind in ranked[:k]:
            stale_sources = await self._stale_sources(spec.sources)
            results.append(
                BehaviorSearchResult(
                    spec=spec,
                    score=sum(stored_key),
                    match_kind=match_kind,
                    stale=bool(stale_sources),
                    stale_sources=stale_sources,
                )
            )
        return tuple(results)

    @staticmethod
    def _lexical_score(spec: BehaviorSpec, query_tokens: frozenset[str]) -> float:
        if not query_tokens:
            return 0.0
        overlap = query_tokens & _tokens(spec.search_text())
        return len(overlap) / len(query_tokens)

    async def _stale_sources(
        self,
        sources: tuple[BehaviorSource, ...],
    ) -> tuple[BehaviorSource, ...]:
        if self._source_validator is None:
            return ()
        stale = []
        for source in sources:
            freshness = await self._source_validator.validate(source)
            if not freshness.fresh:
                stale.append(source)
        return tuple(stale)


__all__ = ["InMemoryBehaviorKnowledgeIndex"]
