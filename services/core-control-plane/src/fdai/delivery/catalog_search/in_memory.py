"""In-memory atomic semantic generations for tests and offline validation."""

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
    CatalogGenerationValidationSnapshot,
    CatalogSearchDocument,
    CatalogSearchResult,
    Embedder,
    build_document_digest_manifest,
    catalog_search_document_digest,
)
from fdai.shared.providers.knowledge import cosine_similarity

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")
_MIN_SCORE = 0.2
_NON_DISCRIMINATING_ENGLISH_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "every",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "prior",
        "rule",
        "that",
        "the",
        "this",
        "to",
        "up",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


class InMemoryCatalogSemanticIndex:
    """Concrete candidate-only index with atomic generation activation.

    This adapter performs no provider reads and grants no policy or action
    authority. A generation is visible only after staging and validated pointer
    activation under one lock.
    """

    def __init__(self, *, embedder: Embedder | None = None) -> None:
        self._embedder = embedder
        self._documents: dict[str, CatalogSearchDocument] = {}
        self._generations: dict[
            str, tuple[CatalogGenerationMetadata, tuple[CatalogSearchDocument, ...]]
        ] = {}
        self._active: dict[CatalogCorpus, str] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int:
        changed = 0
        for document in documents:
            prepared = await self._prepare(document)
            if self._documents.get(prepared.rule_id) != prepared:
                self._documents[prepared.rule_id] = prepared
                changed += 1
        return changed

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        expected = {item.rule_id for item in documents}
        removed = set(self._documents) - expected
        for identifier in removed:
            del self._documents[identifier]
        return len(removed) + await self.upsert(documents)

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int:
        if metadata.state != "staged":
            raise ValueError("only staged semantic generations can be written")
        if not documents:
            raise ValueError("semantic generation documents MUST be non-empty")
        identifiers = [item.rule_id for item in documents]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("semantic generation document ids MUST be unique")
        prepared_rows: list[CatalogSearchDocument] = []
        for item in documents:
            prepared_document = await self._prepare(
                replace(item, corpus=metadata.corpus, generation_id=metadata.generation_id)
            )
            if (
                prepared_document.embedding
                and len(prepared_document.embedding) != metadata.embedding_dimension
            ):
                raise ValueError("semantic generation embedding dimension mismatch")
            prepared_rows.append(prepared_document)
        prepared = tuple(prepared_rows)
        _verify_document_identity(metadata, prepared)
        async with self._lock:
            prior = self._generations.get(metadata.generation_id)
            if prior is not None:
                if prior != (metadata, prepared):
                    raise ValueError("semantic generation id payload conflict")
                return 0
            self._generations[metadata.generation_id] = metadata, prepared
        return len(prepared)

    async def generation_validation_snapshot(
        self,
        generation_id: str,
    ) -> CatalogGenerationValidationSnapshot | None:
        async with self._lock:
            loaded = self._generations.get(generation_id)
            if loaded is None:
                return None
            metadata, documents = loaded
            if metadata.state != "staged":
                raise ValueError("only staged semantic generations can be validated")
            _verify_document_identity(metadata, documents)
            return CatalogGenerationValidationSnapshot(
                metadata=metadata,
                documents=documents,
            )

    async def bind_generation_validation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        validation_receipt_digest: str,
    ) -> CatalogGenerationMetadata:
        async with self._lock:
            try:
                metadata, documents = self._generations[generation_id]
            except KeyError as exc:
                raise ValueError("semantic generation is unavailable") from exc
            if metadata.generation_digest != expected_generation_digest:
                raise ValueError("semantic generation digest mismatch")
            prior = metadata.validation_receipt_digest
            if prior is not None and prior != validation_receipt_digest:
                raise ValueError("semantic generation validation receipt conflict")
            if prior == validation_receipt_digest:
                return metadata
            if metadata.state != "staged":
                raise ValueError("only staged semantic generations can bind validation")
            bound = replace(metadata, validation_receipt_digest=validation_receipt_digest)
            self._generations[generation_id] = bound, documents
            return bound

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        expected_active_generation_id: str | None,
        expected_active_generation_digest: str | None,
        activated_at: datetime,
        expected_validation_receipt_digest: str | None = None,
    ) -> CatalogGenerationMetadata:
        if activated_at.tzinfo is None:
            raise ValueError("semantic generation activation time MUST be timezone-aware")
        if (expected_active_generation_id is None) != (expected_active_generation_digest is None):
            raise ValueError("expected active generation identity MUST be supplied together")
        async with self._lock:
            try:
                metadata, documents = self._generations[generation_id]
            except KeyError as exc:
                raise ValueError("semantic generation is unavailable") from exc
            _verify_document_identity(metadata, documents)
            if metadata.generation_digest != expected_generation_digest:
                raise ValueError("semantic generation digest mismatch")
            if (
                expected_validation_receipt_digest is not None
                and metadata.validation_receipt_digest != expected_validation_receipt_digest
            ):
                raise ValueError("semantic generation validation receipt mismatch")
            active_id = self._active.get(metadata.corpus)
            if metadata.state == "active":
                if active_id == generation_id and metadata.activated_at == activated_at:
                    return metadata
                raise CatalogGenerationStaleError("active semantic generation is stale")
            if metadata.state == "retired":
                raise CatalogGenerationStaleError("active semantic generation is stale")
            if metadata.state != "staged" or metadata.validation_receipt_digest is None:
                raise ValueError("semantic generation is not validated and staged")
            if expected_active_generation_id is None:
                if active_id is not None:
                    raise CatalogGenerationStaleError("active semantic generation is stale")
            elif active_id != expected_active_generation_id:
                raise CatalogGenerationStaleError("active semantic generation is stale")
            else:
                try:
                    prior, prior_documents = self._generations[expected_active_generation_id]
                except KeyError as exc:
                    raise CatalogGenerationStaleError(
                        "active semantic generation is stale"
                    ) from exc
                _verify_document_identity(prior, prior_documents)
                if (
                    prior.generation_digest != expected_active_generation_digest
                    or prior.state != "active"
                ):
                    raise CatalogGenerationStaleError("active semantic generation is stale")
                if prior.activated_at is None or activated_at < prior.activated_at:
                    raise ValueError(
                        "semantic generation activation time precedes active generation"
                    )
            if active_id is not None:
                prior, prior_documents = self._generations[active_id]
                self._generations[active_id] = (
                    replace(prior, state="retired"),
                    prior_documents,
                )
            active = replace(metadata, state="active", activated_at=activated_at)
            self._generations[generation_id] = active, documents
            self._active[metadata.corpus] = generation_id
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
        if rolled_back_at.tzinfo is None:
            raise ValueError("semantic generation rollback time MUST be timezone-aware")
        async with self._lock:
            try:
                target, target_documents = self._generations[target_generation_id]
                current, current_documents = self._generations[expected_active_generation_id]
            except KeyError as exc:
                raise ValueError("semantic rollback generation is unavailable") from exc
            _verify_document_identity(target, target_documents)
            _verify_document_identity(current, current_documents)
            active_id = self._active.get(target.corpus)
            if active_id == target_generation_id:
                if (
                    current.state == "retired"
                    and target.state == "active"
                    and target.activated_at == rolled_back_at
                ):
                    return CatalogGenerationRollbackReceipt(
                        retired_generation=current,
                        reactivated_generation=target,
                        validation_receipt_digest=expected_validation_receipt_digest,
                        ontology_compatibility_receipt=ontology_compatibility_receipt,
                        rolled_back_at=rolled_back_at,
                    )
                raise CatalogGenerationStaleError("active semantic generation is stale")
            if active_id != current.generation_id or current.state != "active":
                raise CatalogGenerationStaleError("active semantic generation is stale")
            if current.generation_digest != expected_active_generation_digest:
                raise ValueError("active semantic generation digest mismatch")
            if target.generation_digest != expected_target_generation_digest:
                raise ValueError("target semantic generation digest mismatch")
            if target.validation_receipt_digest != expected_validation_receipt_digest:
                raise ValueError("target semantic validation receipt mismatch")
            if target.state != "retired" or target.activated_at is None:
                raise ValueError("target semantic generation is not retained")
            retired = replace(current, state="retired")
            reactivated = replace(target, state="active", activated_at=rolled_back_at)
            receipt = CatalogGenerationRollbackReceipt(
                retired_generation=retired,
                reactivated_generation=reactivated,
                validation_receipt_digest=expected_validation_receipt_digest,
                ontology_compatibility_receipt=ontology_compatibility_receipt,
                rolled_back_at=rolled_back_at,
            )
            self._generations[current.generation_id] = retired, current_documents
            self._generations[target.generation_id] = reactivated, target_documents
            self._active[target.corpus] = target.generation_id
            return receipt

    async def active_generation(
        self,
        corpus: CatalogCorpus = "active",
    ) -> CatalogGenerationMetadata | None:
        generation_id = self._active.get(corpus)
        if generation_id is None:
            return None
        metadata, documents = self._generations[generation_id]
        _verify_document_identity(metadata, documents)
        return metadata

    async def search(
        self,
        query: str,
        *,
        k: int = 20,
        corpus: CatalogCorpus = "active",
        expected_catalog_digest: str | None = None,
        candidate_rule_ids: frozenset[str] | None = None,
    ) -> Sequence[CatalogSearchResult]:
        if not 1 <= k <= 100 or not query.strip():
            return ()
        generation = await self.active_generation(corpus)
        documents = tuple(self._documents.values())
        if generation is not None:
            if (
                expected_catalog_digest is not None
                and generation.catalog_digest != expected_catalog_digest
            ):
                raise CatalogGenerationStaleError("active semantic generation is stale")
            documents = self._generations[generation.generation_id][1]
        elif expected_catalog_digest is not None:
            raise CatalogGenerationStaleError("active semantic generation is unavailable")
        query_tokens = _tokens(query)
        query_vector = (
            tuple(await self._embedder.embed(query)) if self._embedder is not None else ()
        )
        ranked: list[tuple[float, CatalogSearchDocument, dict[str, float]]] = []
        for document in documents:
            if candidate_rule_ids is not None and document.rule_id not in candidate_rule_ids:
                continue
            lexical = _lexical_score(document, query_tokens)
            semantic = cosine_similarity(query_vector, document.embedding)
            exact = float(query.casefold().strip() == document.rule_id.casefold())
            score = exact + lexical + max(0.0, semantic)
            if score < _MIN_SCORE:
                continue
            ranked.append(
                (score, document, {"exact": exact, "lexical": lexical, "semantic": semantic})
            )
        ranked.sort(key=lambda item: (-item[0], item[1].rule_id))
        return tuple(
            CatalogSearchResult(
                rule_id=document.rule_id,
                score=score,
                match="exact_id" if components["exact"] else "hybrid",
                components=components,
                corpus=document.corpus,
                generation_id=document.generation_id,
                generation_digest=generation.generation_digest if generation else None,
                catalog_digest=generation.catalog_digest if generation else None,
                document_kind=document.document_kind,
            )
            for score, document, components in ranked[:k]
        )

    async def _prepare(self, document: CatalogSearchDocument) -> CatalogSearchDocument:
        if document.embedding or self._embedder is None:
            return document
        return replace(document, embedding=tuple(await self._embedder.embed(document.text)))


def _tokens(value: str) -> frozenset[str]:
    result: set[str] = set()
    for raw in _TOKEN.findall(value.casefold()):
        if raw.isdecimal() or raw in _NON_DISCRIMINATING_ENGLISH_TOKENS:
            continue
        result.add(raw)
        if re.fullmatch(r"[가-힣]+", raw):
            result.update(raw[index : index + 2] for index in range(len(raw) - 1))
    return frozenset(result)


def _verify_document_identity(
    metadata: CatalogGenerationMetadata,
    documents: tuple[CatalogSearchDocument, ...],
) -> None:
    document_digests = tuple(catalog_search_document_digest(item) for item in documents)
    actual = build_document_digest_manifest(document_digests)
    if metadata.document_digest_manifest != actual:
        raise ValueError("semantic generation document digest manifest mismatch")


def _lexical_score(document: CatalogSearchDocument, query_tokens: frozenset[str]) -> float:
    if not query_tokens:
        return 0.0
    document_tokens = _tokens(
        f"{document.rule_id}\n{document.text}\n{' '.join(document.neighbor_ids)}"
    )
    return len(query_tokens & document_tokens) / len(query_tokens)


__all__ = ["InMemoryCatalogSemanticIndex"]
