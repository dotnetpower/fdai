"""In-memory hybrid semantic index for catalog Rules and typed neighbors."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogGenerationRollbackReceipt,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
    CatalogSearchMatch,
    CatalogSearchResult,
    Embedder,
)
from fdai.shared.providers.knowledge import cosine_similarity

from .generation_rollback import plan_catalog_generation_rollback

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
        self._generations: dict[
            str, tuple[CatalogGenerationMetadata, tuple[CatalogSearchDocument, ...]]
        ] = {}
        self._active_generation_ids: dict[CatalogCorpus, str] = {}
        self._generation_lock = asyncio.Lock()

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

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int:
        """Stage one complete generation without changing visible search results."""

        if metadata.state != "staged":
            raise ValueError("only staged catalog generations can be written")
        if not documents:
            raise ValueError("catalog generation documents MUST be non-empty")
        if len({item.rule_id for item in documents}) != len(documents):
            raise ValueError("catalog generation Rule ids MUST be unique")
        prepared_rows: list[CatalogSearchDocument] = []
        for item in documents:
            prepared_rows.append(
                await self._prepare_document(
                    replace(item, corpus=metadata.corpus, generation_id=metadata.generation_id)
                )
            )
        prepared = tuple(prepared_rows)
        async with self._generation_lock:
            prior = self._generations.get(metadata.generation_id)
            if prior is not None:
                if prior != (metadata, prepared):
                    raise ValueError("catalog generation id payload conflict")
                return 0
            self._generations[metadata.generation_id] = metadata, prepared
            return len(prepared)

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        activated_at: datetime,
    ) -> CatalogGenerationMetadata:
        """Atomically replace one corpus active pointer after validation."""

        async with self._generation_lock:
            try:
                metadata, documents = self._generations[generation_id]
            except KeyError as exc:
                raise ValueError("catalog generation is unavailable") from exc
            if metadata.generation_digest != expected_generation_digest:
                raise ValueError("catalog generation digest mismatch")
            if metadata.state != "staged":
                raise ValueError("only a staged catalog generation can be activated")
            if metadata.validation_receipt_digest is None:
                raise ValueError("catalog generation validation receipt is unavailable")
            prior_active_id = self._active_generation_ids.get(metadata.corpus)
            if prior_active_id is not None:
                prior_metadata, prior_documents = self._generations[prior_active_id]
                self._generations[prior_active_id] = (
                    replace(prior_metadata, state="retired"),
                    prior_documents,
                )
            active = replace(metadata, state="active", activated_at=activated_at)
            self._generations[generation_id] = active, documents
            self._active_generation_ids[metadata.corpus] = generation_id
            return active

    async def rollback_generation(
        self,
        target_generation_id: str,
        *,
        expected_active_generation_id: str,
        expected_active_generation_digest: str,
        expected_target_generation_digest: str,
        expected_validation_receipt_digest: str,
        ontology_compatibility_receipt: OntologyGenerationCompatibilityReceipt,
        rolled_back_at: datetime,
    ) -> CatalogGenerationRollbackReceipt:
        """Atomically restore a retained generation when every pinned identity matches."""

        async with self._generation_lock:
            try:
                target, target_documents = self._generations[target_generation_id]
                current, current_documents = self._generations[expected_active_generation_id]
            except KeyError as exc:
                raise ValueError("catalog rollback generation is unavailable") from exc
            transition = plan_catalog_generation_rollback(
                current=current,
                target=target,
                active_generation_id=self._active_generation_ids.get(target.corpus),
                expected_active_generation_digest=expected_active_generation_digest,
                expected_target_generation_digest=expected_target_generation_digest,
                expected_validation_receipt_digest=expected_validation_receipt_digest,
                ontology_compatibility_receipt=ontology_compatibility_receipt,
                rolled_back_at=rolled_back_at,
            )
            if transition.already_applied:
                return transition.receipt
            self._generations[expected_active_generation_id] = (
                transition.receipt.retired_generation,
                current_documents,
            )
            self._generations[target_generation_id] = (
                transition.receipt.reactivated_generation,
                target_documents,
            )
            self._active_generation_ids[target.corpus] = target_generation_id
            return transition.receipt

    async def active_generation(
        self, corpus: CatalogCorpus = "active"
    ) -> CatalogGenerationMetadata | None:
        generation_id = self._active_generation_ids.get(corpus)
        return self._generations[generation_id][0] if generation_id is not None else None

    async def search(
        self,
        query: str,
        *,
        k: int = 20,
        corpus: CatalogCorpus = "active",
        expected_catalog_digest: str | None = None,
    ) -> Sequence[CatalogSearchResult]:
        documents = tuple(self._documents.values())
        generation = await self.active_generation(corpus)
        if generation is not None:
            if (
                expected_catalog_digest is not None
                and generation.catalog_digest != expected_catalog_digest
            ):
                raise CatalogGenerationStaleError("active catalog generation is stale")
            documents = self._generations[generation.generation_id][1]
        elif expected_catalog_digest is not None:
            raise CatalogGenerationStaleError("active catalog generation is unavailable")
        if not query.strip() or k <= 0 or not documents:
            return ()
        query_tokens = _tokens(query)
        query_vector = (
            tuple(await self._embedder.embed(query)) if self._embedder is not None else ()
        )
        lexical = sorted(
            documents,
            key=lambda item: (-self._lexical_score(item, query_tokens), item.rule_id),
        )
        semantic = sorted(
            documents,
            key=lambda item: (-cosine_similarity(query_vector, item.embedding), item.rule_id),
        )
        lexical_rank = {item.rule_id: rank for rank, item in enumerate(lexical, start=1)}
        semantic_rank = {item.rule_id: rank for rank, item in enumerate(semantic, start=1)}

        ranked: list[tuple[tuple[float, ...], CatalogSearchDocument, CatalogSearchMatch]] = []
        normalized_query = query.strip().casefold()
        for document in documents:
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
            CatalogSearchResult(
                rule_id=document.rule_id,
                score=sum(key),
                match=match,
                components={
                    "exact": key[0],
                    "neighbor": key[1],
                    "reciprocal_rank": key[2],
                    "lexical": key[3],
                    "semantic": key[4],
                },
                corpus=document.corpus,
                generation_id=document.generation_id,
                generation_digest=generation.generation_digest if generation else None,
                catalog_digest=generation.catalog_digest if generation else None,
            )
            for key, document, match in ranked[:k]
        )

    async def _prepare_document(self, document: CatalogSearchDocument) -> CatalogSearchDocument:
        if document.embedding or self._embedder is None:
            return document
        return replace(document, embedding=tuple(await self._embedder.embed(document.text)))

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
