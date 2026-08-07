from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator, PolicyResult, RuleIndex
from fdai.delivery.catalog_search import (
    InMemoryCatalogSemanticIndex,
    load_shipped_catalog_reference_sources,
    publish_shipped_catalog_generation,
)
from fdai.delivery.catalog_search.concept_query import (
    CatalogConceptQuery,
    ConceptFirstCatalogRetriever,
    build_rule_concept_bindings,
    build_rule_search_facets,
)
from fdai.rule_catalog.schema.rule_semantic_generation import RetrievalOperation
from fdai.shared.contracts.models import CheckLogicKind, OntologyReleaseRef

_REPO_ROOT = Path(__file__).resolve().parents[3]


class _Embedder:
    async def embed(self, text: str) -> tuple[float, float, float]:
        del text
        return (1.0, 0.0, 0.0)


async def test_evaluate_query_resolves_exact_active_rego_rule() -> None:
    index = InMemoryCatalogSemanticIndex(embedder=_Embedder())
    generation = await publish_shipped_catalog_generation(
        index=index,
        repo_root=_REPO_ROOT,
        validation_receipt_digest="sha256:" + "f" * 64,
        embedding_space_id="catalog-search-3",
        embedding_model_version="test-embedder:1",
        embedding_dimension=3,
        activated_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    references = load_shipped_catalog_reference_sources(repo_root=_REPO_ROOT)
    rule_index = RuleIndex.build(references.rules)
    retriever = ConceptFirstCatalogRetriever(
        index=index,
        catalog_digest=generation.catalog_digest,
        ontology_release_digest=generation.ontology_release_digest,
        concepts=build_rule_concept_bindings(references.rules),
        facets=build_rule_search_facets(references.rules),
    )

    receipt = await retriever.resolve(
        CatalogConceptQuery(
            text="object-storage.public-access.deny",
            operation=RetrievalOperation.EVALUATE,
            ontology_release_ref=OntologyReleaseRef(digest=generation.ontology_release_digest),
            max_results=1,
        )
    )

    assert receipt.execution_authority is False
    assert len(receipt.results) == 1
    rule_ref, _, version = receipt.results[0].rule_ref.rpartition("@")
    rule = rule_index.rule(rule_ref.removeprefix("rule:"))
    assert str(rule.version) == version
    assert rule.check_logic.kind is CheckLogicKind.REGO

    result = OpaRegoEvaluator(policies_root=_REPO_ROOT / "policies").evaluate(
        rule,
        {"public_access": "enabled"},
    )

    assert isinstance(result, PolicyResult)
    assert result.denied is True
