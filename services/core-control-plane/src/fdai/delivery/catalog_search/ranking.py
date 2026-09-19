"""Shared bilingual candidate ranking for durable and local catalog adapters."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.shared.providers.catalog_search import CatalogSearchDocument
from fdai.shared.providers.knowledge import cosine_similarity

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")
_STOPWORDS = frozenset(
    (
        "a an and are as at be by every for from has have in into is it of on or prior rule "
        "that the this to up was were what when where which who why with"
    ).split()
)


@dataclass(frozen=True, slots=True)
class CatalogRankingPolicy:
    """Finite configurable ranking parameters with no decision authority."""

    minimum_score: float = 0.2
    exact_weight: float = 1.0
    lexical_weight: float = 1.0
    semantic_weight: float = 1.0

    def __post_init__(self) -> None:
        for value in (
            self.minimum_score,
            self.exact_weight,
            self.lexical_weight,
            self.semantic_weight,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 3:
                raise ValueError("catalog ranking values MUST be finite and in [0, 3]")
        if self.exact_weight <= 0 or self.minimum_score > self.exact_weight:
            raise ValueError("catalog ranking policy MUST retain exact identifiers")


def lexical_tokens(value: str) -> frozenset[str]:
    tokens: set[str] = set()
    for raw in _TOKEN.findall(value.casefold()):
        if raw.isdecimal() or raw in _STOPWORDS:
            continue
        tokens.add(raw)
        if re.fullmatch(r"[가-힣]+", raw):
            tokens.update(raw[index : index + 2] for index in range(len(raw) - 1))
    return frozenset(tokens)


def lexical_score(document: CatalogSearchDocument, query_tokens: frozenset[str]) -> float:
    if not query_tokens:
        return 0.0
    tokens = lexical_tokens(
        f"{document.rule_id}\n{document.text}\n{' '.join(document.neighbor_ids)}"
    )
    return len(query_tokens & tokens) / len(query_tokens)


def rank_documents(
    documents: Sequence[CatalogSearchDocument],
    query: str,
    *,
    policy: CatalogRankingPolicy,
    query_vector: Sequence[float] = (),
    semantic_scores: Mapping[str, float] | None = None,
    candidate_rule_ids: frozenset[str] | None = None,
) -> tuple[tuple[float, CatalogSearchDocument, dict[str, float]], ...]:
    """Use identical exact, lexical, semantic, and tie semantics in both adapters."""
    tokens = lexical_tokens(query)
    ranked: list[tuple[float, CatalogSearchDocument, dict[str, float]]] = []
    for document in documents:
        if candidate_rule_ids is not None and document.rule_id not in candidate_rule_ids:
            continue
        exact = float(query.casefold().strip() == document.rule_id.casefold())
        lexical = lexical_score(document, tokens)
        semantic = (
            semantic_scores.get(document.rule_id, 0.0)
            if semantic_scores is not None
            else cosine_similarity(query_vector, document.embedding)
        )
        if not math.isfinite(semantic):
            raise ValueError("catalog semantic score MUST be finite")
        semantic = max(0.0, min(1.0, semantic))
        score = (
            policy.exact_weight * exact
            + policy.lexical_weight * lexical
            + policy.semantic_weight * semantic
        )
        if score >= policy.minimum_score:
            ranked.append(
                (score, document, {"exact": exact, "lexical": lexical, "semantic": semantic})
            )
    ranked.sort(key=lambda item: (-item[0], item[1].rule_id))
    return tuple(ranked)
