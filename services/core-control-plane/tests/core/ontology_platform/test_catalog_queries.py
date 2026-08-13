"""Exact-generation contracts for read-only catalog ontology functions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform.catalog_queries import (
    CATALOG_SEARCH_PURPOSE,
    CATALOG_SEARCH_RULES_FUNCTION_NAME,
    ObjectiveRuleResolver,
    catalog_search_rules_function,
    catalog_search_rules_function_type,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.rule_catalog.schema.control_objective import (
    ControlObjective,
    ControlObjectiveState,
    control_objective_content_hash,
)
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    RuleObjectiveBinding,
    rule_objective_binding_content_hash,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)

CATALOG_DIGEST = "sha256:" + ("a" * 64)
SCHEMA_DIGEST = "sha256:" + ("b" * 64)
VALIDATION_DIGEST = "sha256:" + ("d" * 64)
NOW = datetime(2026, 8, 12, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[5]
OBJECTIVE_PATH = (
    REPO_ROOT
    / "rule-catalog"
    / "control-objectives"
    / "reliability.node-pool.zone-failure-tolerance.yaml"
)
BINDING_PATH = (
    REPO_ROOT
    / "rule-catalog"
    / "rule-objective-bindings"
    / "binding.node-pool-zone-resilience.yaml"
)


async def _active_index(
    *,
    release_digest: str,
    documents: tuple[CatalogSearchDocument, ...] | None = None,
) -> InMemoryCatalogSemanticIndex:
    index = InMemoryCatalogSemanticIndex()
    documents = documents or (
        CatalogSearchDocument(
            rule_id="network.nsg-open-deny",
            text="deny an open network security group",
            neighbor_ids=("network.nsg",),
        ),
    )
    document_manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=CATALOG_DIGEST,
        semantic_schema_digest=SCHEMA_DIGEST,
        ontology_release_digest=release_digest,
        embedding_space_id="rule-search-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=document_manifest,
    )
    metadata = CatalogGenerationMetadata(
        generation_id="rules-active-1",
        generation_digest=generation_digest,
        corpus="active",
        catalog_digest=CATALOG_DIGEST,
        semantic_schema_digest=SCHEMA_DIGEST,
        ontology_release_digest=release_digest,
        embedding_space_id="rule-search-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=document_manifest,
        validation_receipt_digest=VALIDATION_DIGEST,
    )
    await index.stage_generation(metadata, documents)
    await index.activate_generation(
        metadata.generation_id,
        expected_generation_digest=metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
    )
    return index


def _reviewed_policy_abstractions() -> tuple[ControlObjective, RuleObjectiveBinding]:
    objective_raw = yaml.safe_load(OBJECTIVE_PATH.read_text(encoding="utf-8"))
    objective_raw["state"] = "reviewed"
    objective_draft = ControlObjective.model_validate(objective_raw)
    objective_digest = control_objective_content_hash(objective_draft)
    objective_raw["content_digest"] = objective_digest
    objective_raw["provenance"]["content_hash"] = objective_digest
    objective = ControlObjective.model_validate(objective_raw)

    binding_raw = yaml.safe_load(BINDING_PATH.read_text(encoding="utf-8"))
    binding_raw["state"] = "reviewed"
    binding_raw["objective"]["content_digest"] = objective.content_digest
    binding_draft = RuleObjectiveBinding.model_validate(binding_raw)
    binding_digest = rule_objective_binding_content_hash(binding_draft)
    binding_raw["content_digest"] = binding_digest
    binding_raw["provenance"]["content_hash"] = binding_digest
    return objective, RuleObjectiveBinding.model_validate(binding_raw)


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
    expected_document = CatalogSearchDocument(
        rule_id="network.nsg-open-deny",
        text="deny an open network security group",
        neighbor_ids=("network.nsg",),
    )
    expected_manifest = build_document_digest_manifest(
        (catalog_search_document_digest(expected_document),)
    )
    expected_generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=CATALOG_DIGEST,
        semantic_schema_digest=SCHEMA_DIGEST,
        ontology_release_digest=release.digest,
        embedding_space_id="rule-search-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=expected_manifest,
    )
    assert result["retrieval_receipt"]["generation_digest"] == expected_generation_digest
    assert result["authority"] == "candidate_only"
    assert result["execution_authority"] is False
    assert CATALOG_SEARCH_RULES_FUNCTION_NAME in {
        item.name for item in operational_function_types(())
    }


async def test_reviewed_objective_narrows_exact_rule_candidates_without_authority() -> None:
    objective, binding = _reviewed_policy_abstractions()
    declaration = catalog_search_rules_function_type()
    release = build_ontology_release(function_types=(declaration,))
    documents = (
        CatalogSearchDocument(
            rule_id="kubernetes-node-pool.multi-zone",
            text="node pool zone resilience",
            neighbor_ids=("kubernetes-node-pool",),
        ),
        CatalogSearchDocument(
            rule_id="kubernetes-node-pool.minimum-count",
            text="node pool",
            neighbor_ids=("kubernetes-node-pool",),
        ),
    )
    resolver = ObjectiveRuleResolver(
        control_objectives=(objective,),
        objective_bindings=(binding,),
        active_rule_digests={binding.rule.ref: binding.rule.content_digest},
    )
    function = catalog_search_rules_function(
        release,
        index=await _active_index(release_digest=release.digest, documents=documents),
        catalog_digest=CATALOG_DIGEST,
        objective_resolver=resolver,
    )

    result = await function(
        {
            "query": "node pool",
            "operation": "discover",
            "corpus": "active",
            "limit": 1,
            "objective_refs": [objective.ref],
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(CATALOG_SEARCH_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert [item["rule_ref"] for item in result["candidates"]] == [
        "kubernetes-node-pool.multi-zone"
    ]
    assert result["objective_resolution"]["state"] == "resolved"
    assert result["objective_resolution"]["objective_pins"] == [
        {"ref": objective.ref, "content_digest": objective.content_digest}
    ]
    assert result["objective_resolution"]["binding_pins"] == [
        {"ref": binding.ref, "content_digest": binding.content_digest}
    ]
    assert result["objective_resolution"]["rule_pins"] == [
        {"ref": binding.rule.ref, "content_digest": binding.rule.content_digest}
    ]
    assert result["objective_resolution"]["execution_authority"] is False
    assert result["candidates"][0]["authority"] == "candidate_only"
    assert result["authority"] == "candidate_only"
    assert result["execution_authority"] is False

    unscoped_result = await function(
        {
            "query": "node pool",
            "operation": "discover",
            "corpus": "active",
            "limit": 1,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(CATALOG_SEARCH_PURPOSE,),
        ),
    )
    assert isinstance(unscoped_result, dict)
    assert unscoped_result["candidates"][0]["rule_ref"] == ("kubernetes-node-pool.minimum-count")
    assert (
        unscoped_result["retrieval_receipt"]["query_digest"]
        != result["retrieval_receipt"]["query_digest"]
    )


async def test_candidate_objective_falls_back_to_full_search_without_authority() -> None:
    reviewed_objective, binding = _reviewed_policy_abstractions()
    candidate_objective = reviewed_objective.model_copy(
        update={"state": ControlObjectiveState.CANDIDATE}
    )
    declaration = catalog_search_rules_function_type()
    release = build_ontology_release(function_types=(declaration,))
    documents = (
        CatalogSearchDocument(
            rule_id="kubernetes-node-pool.multi-zone",
            text="node pool zone resilience",
            neighbor_ids=("kubernetes-node-pool",),
        ),
        CatalogSearchDocument(
            rule_id="kubernetes-node-pool.minimum-count",
            text="node pool minimum count",
            neighbor_ids=("kubernetes-node-pool",),
        ),
    )
    function = catalog_search_rules_function(
        release,
        index=await _active_index(release_digest=release.digest, documents=documents),
        catalog_digest=CATALOG_DIGEST,
        objective_resolver=ObjectiveRuleResolver(
            control_objectives=(candidate_objective,),
            objective_bindings=(binding,),
            active_rule_digests={binding.rule.ref: binding.rule.content_digest},
        ),
    )

    result = await function(
        {
            "query": "node pool",
            "operation": "discover",
            "corpus": "active",
            "limit": 5,
            "objective_refs": [candidate_objective.ref],
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(CATALOG_SEARCH_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert {item["rule_ref"] for item in result["candidates"]} == {
        "kubernetes-node-pool.minimum-count",
        "kubernetes-node-pool.multi-zone",
    }
    assert result["objective_resolution"] == {
        "state": "degraded",
        "requested_objective_refs": [candidate_objective.ref],
        "candidate_rule_ids": [],
        "objective_pins": [],
        "binding_pins": [],
        "rule_pins": [],
        "degraded_reason": "objective_not_reviewed",
        "fallback_applied": True,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    assert result["execution_authority"] is False


@pytest.mark.parametrize(
    ("objective_refs", "active_rule_digests", "expected_reason"),
    [
        (("missing.objective@1.0.0",), None, "objective_not_found"),
        (None, {"use_binding_ref": "sha256:" + ("f" * 64)}, "rule_pin_stale"),
    ],
)
def test_objective_resolution_degrades_atomically_without_verified_pins(
    objective_refs: tuple[str, ...] | None,
    active_rule_digests: dict[str, str] | None,
    expected_reason: str,
) -> None:
    objective, binding = _reviewed_policy_abstractions()
    resolved_active_digests = active_rule_digests or {binding.rule.ref: binding.rule.content_digest}
    if "use_binding_ref" in resolved_active_digests:
        resolved_active_digests = {binding.rule.ref: resolved_active_digests["use_binding_ref"]}
    resolver = ObjectiveRuleResolver(
        control_objectives=(objective,),
        objective_bindings=(binding,),
        active_rule_digests=resolved_active_digests,
    )

    resolution = resolver.resolve(
        objective_refs or (objective.ref,),
        corpus=RuleCorpus.ACTIVE,
    )

    assert resolution.state.value == "degraded"
    assert resolution.degraded_reason == expected_reason
    assert resolution.fallback_applied is True
    assert resolution.candidate_rule_ids == ()
    assert resolution.objective_pins == ()
    assert resolution.binding_pins == ()
    assert resolution.rule_pins == ()


def test_candidate_binding_and_discovery_corpus_cannot_narrow_rules() -> None:
    objective, reviewed_binding = _reviewed_policy_abstractions()
    candidate_binding = reviewed_binding.model_copy(update={"state": BindingState.CANDIDATE})
    candidate_resolver = ObjectiveRuleResolver(
        control_objectives=(objective,),
        objective_bindings=(candidate_binding,),
        active_rule_digests={reviewed_binding.rule.ref: reviewed_binding.rule.content_digest},
    )
    reviewed_resolver = ObjectiveRuleResolver(
        control_objectives=(objective,),
        objective_bindings=(reviewed_binding,),
        active_rule_digests={reviewed_binding.rule.ref: reviewed_binding.rule.content_digest},
    )

    candidate_resolution = candidate_resolver.resolve(
        (objective.ref,),
        corpus=RuleCorpus.ACTIVE,
    )
    discovery_resolution = reviewed_resolver.resolve(
        (objective.ref,),
        corpus=RuleCorpus.DISCOVERY,
    )

    assert candidate_resolution.degraded_reason == "binding_unavailable"
    assert candidate_resolution.fallback_applied is True
    assert discovery_resolution.degraded_reason == "objective_resolution_active_only"
    assert discovery_resolution.fallback_applied is True


def test_malformed_versioned_rule_ref_cannot_narrow_candidates() -> None:
    objective, binding = _reviewed_policy_abstractions()
    malformed_rule_ref = f"{binding.rule.ref}@1.0.0"
    malformed_draft = binding.model_copy(
        update={"rule": binding.rule.model_copy(update={"ref": malformed_rule_ref})}
    )
    malformed_digest = rule_objective_binding_content_hash(malformed_draft)
    malformed_binding = malformed_draft.model_copy(
        update={
            "content_digest": malformed_digest,
            "provenance": malformed_draft.provenance.model_copy(
                update={"content_hash": malformed_digest}
            ),
        }
    )
    resolver = ObjectiveRuleResolver(
        control_objectives=(objective,),
        objective_bindings=(malformed_binding,),
        active_rule_digests={malformed_rule_ref: binding.rule.content_digest},
    )

    resolution = resolver.resolve((objective.ref,), corpus=RuleCorpus.ACTIVE)

    assert resolution.degraded_reason == "rule_ref_invalid"
    assert resolution.fallback_applied is True
    assert resolution.candidate_rule_ids == ()
    assert resolution.rule_pins == ()


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
