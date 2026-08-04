"""In-memory hybrid semantic index for catalog Rules and typed neighbors."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from fdai.shared.providers.catalog_search import (
    CatalogSearchDocument,
    CatalogSearchMatch,
    CatalogSearchResult,
    Embedder,
)
from fdai.shared.providers.knowledge import cosine_similarity

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")
_RRF_K = 60.0
_MIN_LEXICAL = 0.2
_MIN_SEMANTIC = 0.35


def _tokens(value: str) -> frozenset[str]:
    tokens: set[str] = set()
    for raw in _TOKEN.findall(value.casefold()):
        tokens.add(raw)
        if re.fullmatch(r"[가-힣]+", raw):
            tokens.update(raw[index : index + 2] for index in range(len(raw) - 1))
    return frozenset(tokens)


class InMemoryCatalogSemanticIndex:
    def __init__(self, *, embedder: Embedder | None = None) -> None:
        self._embedder = embedder
        self._documents: dict[str, CatalogSearchDocument] = {}

    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int:
        changed = 0
        for document in documents:
            stored = document
            if not stored.embedding and self._embedder is not None:
                stored = replace(
                    stored,
                    embedding=tuple(await self._embedder.embed(stored.text)),
                )
            if self._documents.get(stored.rule_id) != stored:
                self._documents[stored.rule_id] = stored
                changed += 1
        return changed

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        expected_ids = {document.rule_id for document in documents}
        removed_ids = set(self._documents) - expected_ids
        for rule_id in removed_ids:
            del self._documents[rule_id]
        return len(removed_ids) + await self.upsert(documents)

    async def search(self, query: str, *, k: int = 20) -> Sequence[CatalogSearchResult]:
        if not query.strip() or k <= 0 or not self._documents:
            return ()
        query_tokens = _tokens(query)
        query_vector = (
            tuple(await self._embedder.embed(query)) if self._embedder is not None else ()
        )
        lexical = sorted(
            self._documents.values(),
            key=lambda item: (-self._lexical_score(item, query_tokens), item.rule_id),
        )
        semantic = sorted(
            self._documents.values(),
            key=lambda item: (-cosine_similarity(query_vector, item.embedding), item.rule_id),
        )
        lexical_rank = {item.rule_id: rank for rank, item in enumerate(lexical, start=1)}
        semantic_rank = {item.rule_id: rank for rank, item in enumerate(semantic, start=1)}

        ranked: list[tuple[tuple[float, ...], CatalogSearchDocument, CatalogSearchMatch]] = []
        normalized_query = query.strip().casefold()
        for document in self._documents.values():
            exact = normalized_query == document.rule_id.casefold()
            lexical_score = self._lexical_score(document, query_tokens)
            semantic_score = cosine_similarity(query_vector, document.embedding)
            neighbor_tokens = _tokens(" ".join(document.neighbor_ids))
            neighbor_score = (
                len(query_tokens & neighbor_tokens) / len(query_tokens) if query_tokens else 0.0
            )
            if (
                not exact
                and lexical_score < _MIN_LEXICAL
                and semantic_score < _MIN_SEMANTIC
                and neighbor_score == 0.0
            ):
                continue
            reciprocal_rank = 1.0 / (_RRF_K + lexical_rank[document.rule_id])
            if query_vector and document.embedding:
                reciprocal_rank += 1.0 / (_RRF_K + semantic_rank[document.rule_id])
            key = (
                float(exact),
                neighbor_score,
                reciprocal_rank,
                lexical_score,
                semantic_score,
            )
            ranked.append((key, document, "exact_id" if exact else "hybrid"))
        ranked.sort(key=lambda item: item[1].rule_id)
        ranked.sort(key=lambda item: item[0], reverse=True)
        return tuple(
            CatalogSearchResult(rule_id=document.rule_id, score=sum(key), match=match)
            for key, document, match in ranked[:k]
        )

    @staticmethod
    def _lexical_score(
        document: CatalogSearchDocument,
        query_tokens: frozenset[str],
    ) -> float:
        if not query_tokens:
            return 0.0
        document_tokens = _tokens(f"{document.rule_id}\n{document.text}")
        return len(query_tokens & document_tokens) / len(query_tokens)


__all__ = ["InMemoryCatalogSemanticIndex"]
