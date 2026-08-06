from __future__ import annotations

from datetime import UTC, datetime

import pytest
from jsonschema import Draft202012Validator

from fdai.core.ontology_platform import FunctionInvocationContext
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.delivery.catalog_search.concept_query import (
    CatalogConceptQuery,
    ConceptFirstCatalogRetriever,
    RuleSearchFacet,
)
from fdai.delivery.catalog_search.ontology_function import (
    build_catalog_query_function_registry,
    catalog_query_function_type,
    project_catalog_retrieval_receipt,
)
from fdai.rule_catalog.schema.rule_semantic_generation import RetrievalOperation
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
)

_CATALOG = "sha256:" + "a" * 64
_GENERATION = "sha256:" + "b" * 64
_SCHEMA = "sha256:" + "c" * 64
_RELEASE = "sha256:" + "d" * 64
_VALIDATION = "sha256:" + "e" * 64


class _Embedder:
    async def embed(self, text: str):  # type: ignore[no-untyped-def]
        return (1.0, 0.0, 0.0) if "public" in text.casefold() else (0.0, 1.0, 0.0)


async def _resolver() -> ConceptFirstCatalogRetriever:
    index = InMemoryCatalogSemanticIndex(embedder=_Embedder())
    metadata = CatalogGenerationMetadata(
        generation_id="generation-active",
        generation_digest=_GENERATION,
        corpus="active",
        catalog_digest=_CATALOG,
        semantic_schema_digest=_SCHEMA,
        ontology_release_digest=_RELEASE,
        embedding_space_id="catalog-search-3",
        embedding_model_version="test:1",
        embedding_dimension=3,
        validation_receipt_digest=_VALIDATION,
    )
    await index.stage_generation(
        metadata,
        (
            CatalogSearchDocument(
                "object-storage.public-access.deny",
                "Block public object storage access",
                ("object-storage", "property.object-storage.public_access"),
            ),
            CatalogSearchDocument(
                "object-storage.versioning-enabled",
                "Enable object storage versioning",
                ("object-storage", "property.object-storage.versioning"),
            ),
        ),
    )
    await index.activate_generation(
        metadata.generation_id,
        expected_generation_digest=metadata.generation_digest,
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    return ConceptFirstCatalogRetriever(
        index=index,
        catalog_digest=_CATALOG,
        ontology_release_digest=_RELEASE,
        concepts={
            "concept.public-access": frozenset({"object-storage.public-access.deny"}),
            "concept.object-storage": frozenset(
                {
                    "object-storage.public-access.deny",
                    "object-storage.versioning-enabled",
                }
            ),
        },
        facets={
            "object-storage.public-access.deny": RuleSearchFacet(
                "object-storage.public-access.deny", "1.0.0", "object-storage", "security"
            ),
            "object-storage.versioning-enabled": RuleSearchFacet(
                "object-storage.versioning-enabled", "1.0.0", "object-storage", "reliability"
            ),
        },
    )


async def test_concept_first_query_limits_hybrid_results() -> None:
    resolver = await _resolver()
    receipt = await resolver.resolve(
        CatalogConceptQuery(
            text="Which policy blocks public storage?",
            operation=RetrievalOperation.EXPLAIN,
            concept_refs=("concept.object-storage", "concept.public-access"),
            resource_types=("object-storage",),
            categories=("security",),
        )
    )

    assert [item.rule_ref for item in receipt.results] == [
        "rule:object-storage.public-access.deny@1.0.0"
    ]
    assert receipt.execution_authority is False
    assert receipt.generation_digest == _GENERATION


async def test_unknown_concept_requires_clarification_without_results() -> None:
    resolver = await _resolver()
    receipt = await resolver.resolve(
        CatalogConceptQuery(
            text="Find the quantum policy",
            operation=RetrievalOperation.DISCOVER,
            concept_refs=("concept.unknown",),
        )
    )

    assert receipt.clarification_required is True
    assert receipt.unresolved_terms == ("concept.unknown",)
    assert receipt.results == ()


async def test_stale_ontology_release_blocks_ranking() -> None:
    resolver = await _resolver()
    resolver._ontology_release_digest = "sha256:" + "f" * 64

    receipt = await resolver.resolve(
        CatalogConceptQuery(
            text="Explain public storage policy",
            operation=RetrievalOperation.EXPLAIN,
        )
    )

    assert receipt.semantic_state.value == "stale"
    assert receipt.degraded_reason == "ontology-release-stale"
    assert receipt.results == ()


def test_discovery_corpus_cannot_request_evaluation() -> None:
    with pytest.raises(ValueError, match="active corpus"):
        CatalogConceptQuery(
            text="Evaluate this candidate",
            operation=RetrievalOperation.EVALUATE,
            corpus=RuleCorpus.DISCOVERY,
        )


def test_query_array_control_characters_are_rejected() -> None:
    with pytest.raises(ValueError, match="bounded text"):
        CatalogConceptQuery(
            text="Explain storage policy",
            operation=RetrievalOperation.EXPLAIN,
            intent_ids=("intent.ignore\ninstructions",),
        )


async def test_catalog_query_function_projection_is_strict_and_read_only() -> None:
    resolver = await _resolver()
    receipt = await resolver.resolve(
        CatalogConceptQuery(
            text="Explain public storage policy",
            operation=RetrievalOperation.EXPLAIN,
            concept_refs=("concept.public-access",),
        )
    )
    projected = project_catalog_retrieval_receipt(receipt)
    declaration = catalog_query_function_type()

    Draft202012Validator(declaration.output_schema).validate(projected)
    assert declaration.name == "catalog.search_rules"
    assert declaration.kind.value == "query"
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False
    assert projected["execution_authority"] is False


async def test_catalog_query_function_registry_invokes_with_exact_release_receipt() -> None:
    declaration = catalog_query_function_type()
    registry = build_catalog_query_function_registry(
        retriever=await _resolver(),
        release=build_ontology_release(function_types=(declaration,)),
    )

    result, receipt = await registry.invoke_with_receipt(
        declaration.name,
        {
            "text": "Explain public storage policy",
            "operation": "explain",
            "corpus": "active",
            "intent_ids": [],
            "concept_refs": ["concept.public-access"],
            "resource_types": [],
            "categories": [],
            "max_results": 20,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("rule_lookup",),
        ),
    )

    assert isinstance(result, dict)
    assert result["status"] == "matched"
    assert result["execution_authority"] is False
    assert receipt.function_ref.name == "catalog.search_rules"


async def test_catalog_query_function_registry_rejects_unowned_agent() -> None:
    declaration = catalog_query_function_type()
    registry = build_catalog_query_function_registry(
        retriever=await _resolver(),
        release=build_ontology_release(function_types=(declaration,)),
    )

    with pytest.raises(PermissionError, match="agent is not allowed"):
        await registry.invoke_with_receipt(
            declaration.name,
            {
                "text": "Explain public storage policy",
                "operation": "explain",
                "corpus": "active",
                "intent_ids": [],
                "concept_refs": [],
                "resource_types": [],
                "categories": [],
                "max_results": 20,
            },
            context=FunctionInvocationContext(
                caller_agent="Thor",
                caller_role=CeilingRole.READER,
                purposes=("rule_lookup",),
            ),
        )
