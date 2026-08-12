"""Exact-generation contracts for read-only catalog ontology functions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.catalog_queries import (
    CATALOG_SEARCH_PURPOSE,
    CATALOG_SEARCH_RULES_FUNCTION_NAME,
    catalog_search_rules_function,
    catalog_search_rules_function_type,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
)

CATALOG_DIGEST = "sha256:" + ("a" * 64)
SCHEMA_DIGEST = "sha256:" + ("b" * 64)
GENERATION_DIGEST = "sha256:" + ("c" * 64)
VALIDATION_DIGEST = "sha256:" + ("d" * 64)
NOW = datetime(2026, 8, 12, tzinfo=UTC)


async def _active_index(*, release_digest: str) -> InMemoryCatalogSemanticIndex:
    index = InMemoryCatalogSemanticIndex()
    metadata = CatalogGenerationMetadata(
        generation_id="rules-active-1",
        generation_digest=GENERATION_DIGEST,
        corpus="active",
        catalog_digest=CATALOG_DIGEST,
        semantic_schema_digest=SCHEMA_DIGEST,
        ontology_release_digest=release_digest,
        embedding_space_id="rule-search-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        validation_receipt_digest=VALIDATION_DIGEST,
    )
    await index.stage_generation(
        metadata,
        (
            CatalogSearchDocument(
                rule_id="network.nsg-open-deny",
                text="deny an open network security group",
                neighbor_ids=("network.nsg",),
            ),
        ),
    )
    await index.activate_generation(
        metadata.generation_id,
        expected_generation_digest=metadata.generation_digest,
        activated_at=NOW,
    )
    return index


async def test_search_rules_returns_exact_generation_candidates_without_authority() -> None:
    declaration = catalog_search_rules_function_type()
    release = build_ontology_release(function_types=(declaration,))
    function = catalog_search_rules_function(
        release,
        index=await _active_index(release_digest=release.digest),
        catalog_digest=CATALOG_DIGEST,
    )

    result = await function(
        {
            "query": "open network security group",
            "operation": "discover",
            "corpus": "active",
            "limit": 5,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(CATALOG_SEARCH_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert result["candidates"] == [
        {
            "rule_ref": "network.nsg-open-deny",
            "rank": 1,
            "components": {"exact": 0.0, "lexical": 1.0, "semantic": 0.0},
            "authority": "candidate_only",
        }
    ]
    assert result["retrieval_receipt"]["generation_digest"] == GENERATION_DIGEST
    assert result["authority"] == "candidate_only"
    assert result["execution_authority"] is False
    assert CATALOG_SEARCH_RULES_FUNCTION_NAME in {
        item.name for item in operational_function_types(())
    }


async def test_search_rules_rejects_generation_for_another_release() -> None:
    declaration = catalog_search_rules_function_type()
    release = build_ontology_release(function_types=(declaration,))
    function = catalog_search_rules_function(
        release,
        index=await _active_index(release_digest="sha256:" + ("e" * 64)),
        catalog_digest=CATALOG_DIGEST,
    )

    with pytest.raises(RuntimeError, match="identity is stale"):
        await function(
            {
                "query": "open network security group",
                "operation": "discover",
                "corpus": "active",
                "limit": 5,
            },
            FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=(CATALOG_SEARCH_PURPOSE,),
            ),
        )
