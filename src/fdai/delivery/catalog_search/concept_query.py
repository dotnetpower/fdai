"""Concept-first Rule retrieval over one exact active index generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.rule_catalog.schema.rule_semantic_generation import (
    CatalogRetrievalReceipt,
    RetrievalOperation,
    RetrievalRank,
    SemanticAvailability,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus, query_digest
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationStaleError,
    CatalogSemanticIndex,
)

_MAX_TERMS = 32


@dataclass(frozen=True, slots=True)
class CatalogConceptQuery:
    """Typed, bounded interpretation supplied to catalog.search_rules."""

    text: str
    operation: RetrievalOperation
    corpus: RuleCorpus = RuleCorpus.ACTIVE
    intent_ids: tuple[str, ...] = ()
    concept_refs: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    max_results: int = 20

    def __post_init__(self) -> None:
        if (
            not self.text.strip()
            or len(self.text) > 4096
            or any(ord(character) < 32 for character in self.text)
        ):
            raise ValueError("catalog concept query text MUST be bounded and non-empty")
        for name, values in (
            ("intent_ids", self.intent_ids),
            ("concept_refs", self.concept_refs),
            ("resource_types", self.resource_types),
            ("categories", self.categories),
        ):
            if len(values) > _MAX_TERMS or values != tuple(sorted(set(values))):
                raise ValueError(f"catalog concept query {name} MUST be unique and ordered")
            if any(_invalid_term(item) for item in values):
                raise ValueError(f"catalog concept query {name} MUST contain bounded text")
        if not 1 <= self.max_results <= 100:
            raise ValueError("catalog concept query max_results MUST be in [1, 100]")
        if self.operation in {RetrievalOperation.EVALUATE, RetrievalOperation.ACTION_DRAFT}:
            if self.corpus is not RuleCorpus.ACTIVE:
                raise ValueError("evaluation and action draft queries MUST use active corpus")


@dataclass(frozen=True, slots=True)
class RuleSearchFacet:
    rule_id: str
    rule_version: str
    resource_type: str
    category: str


def _invalid_term(value: str) -> bool:
    return not value or any(ord(character) < 32 for character in value)


def build_rule_search_facets(rules: Sequence[Rule]) -> Mapping[str, RuleSearchFacet]:
    """Project exact active Rule identity and deterministic filter facets."""

    return {
        rule.id: RuleSearchFacet(
            rule_id=rule.id,
            rule_version=str(rule.version),
            resource_type=rule.resource_type,
            category=rule.category.value,
        )
        for rule in rules
    }


def build_rule_concept_bindings(rules: Sequence[Rule]) -> Mapping[str, frozenset[str]]:
    """Build OPA-free exact catalog adjacency for reviewed Rule references."""

    bindings: dict[str, set[str]] = {}
    for rule in rules:
        references = {
            rule.resource_type,
            rule.remediates,
            *rule.triggered_by,
            *rule.evaluates,
        }
        for reference in references:
            bindings.setdefault(reference, set()).add(rule.id)
    return {reference: frozenset(rule_ids) for reference, rule_ids in sorted(bindings.items())}


class ConceptFirstCatalogRetriever:
    """Resolve ontology concepts before invoking hybrid Rule ranking."""

    def __init__(
        self,
        *,
        index: CatalogSemanticIndex,
        catalog_digest: str,
        concepts: Mapping[str, frozenset[str]],
        facets: Mapping[str, RuleSearchFacet],
    ) -> None:
        self._index = index
        self._catalog_digest = catalog_digest
        self._concepts = dict(concepts)
        self._facets = dict(facets)

    async def resolve(self, query: CatalogConceptQuery) -> CatalogRetrievalReceipt:
        unresolved = tuple(sorted(set(query.concept_refs) - self._concepts.keys()))
        if unresolved:
            return CatalogRetrievalReceipt(
                query_digest=query_digest(query.text),
                operation=query.operation,
                corpus=query.corpus,
                catalog_digest=self._catalog_digest,
                semantic_state=SemanticAvailability.UNAVAILABLE,
                degraded_reason="concept-unresolved",
                unresolved_terms=unresolved,
                clarification_required=True,
                results=(),
            )
        corpus: CatalogCorpus = query.corpus.value
        generation = await self._index.active_generation(corpus)
        if generation is None:
            return self._degraded(query, SemanticAvailability.UNAVAILABLE, "generation-unavailable")
        if generation.catalog_digest != self._catalog_digest:
            return self._degraded(
                query,
                SemanticAvailability.STALE,
                "generation-stale",
                generation_digest=generation.generation_digest,
            )
        allowed: set[str] | None = None
        for concept_ref in query.concept_refs:
            concept_rules = set(self._concepts[concept_ref])
            allowed = concept_rules if allowed is None else allowed.intersection(concept_rules)
        search_text = "\n".join(
            (
                query.text,
                *query.intent_ids,
                *query.concept_refs,
                *query.resource_types,
                *query.categories,
            )
        )
        try:
            ranked = await self._index.search(
                search_text,
                k=min(100, max(query.max_results, query.max_results * 4)),
                corpus=corpus,
                expected_catalog_digest=self._catalog_digest,
            )
        except CatalogGenerationStaleError:
            return self._degraded(
                query,
                SemanticAvailability.STALE,
                "generation-stale",
                generation_digest=generation.generation_digest,
            )
        results: list[RetrievalRank] = []
        for candidate in ranked:
            facet = self._facets.get(candidate.rule_id)
            if facet is None:
                continue
            if allowed is not None and candidate.rule_id not in allowed:
                continue
            if query.resource_types and facet.resource_type not in query.resource_types:
                continue
            if query.categories and facet.category not in query.categories:
                continue
            results.append(
                RetrievalRank(
                    rule_ref=f"rule:{facet.rule_id}@{facet.rule_version}",
                    rank=len(results) + 1,
                    components=tuple(sorted(candidate.components.items())),
                )
            )
            if len(results) >= query.max_results:
                break
        return CatalogRetrievalReceipt(
            query_digest=query_digest(query.text),
            operation=query.operation,
            corpus=query.corpus,
            catalog_digest=self._catalog_digest,
            semantic_state=SemanticAvailability.AVAILABLE,
            generation_digest=generation.generation_digest,
            results=tuple(results),
            truncated=len(ranked) > len(results),
        )

    def _degraded(
        self,
        query: CatalogConceptQuery,
        state: SemanticAvailability,
        reason: str,
        *,
        generation_digest: str | None = None,
    ) -> CatalogRetrievalReceipt:
        return CatalogRetrievalReceipt(
            query_digest=query_digest(query.text),
            operation=query.operation,
            corpus=query.corpus,
            catalog_digest=self._catalog_digest,
            semantic_state=state,
            generation_digest=generation_digest,
            degraded_reason=reason,
            results=(),
        )


__all__ = [
    "CatalogConceptQuery",
    "ConceptFirstCatalogRetriever",
    "RuleSearchFacet",
    "build_rule_concept_bindings",
    "build_rule_search_facets",
]
