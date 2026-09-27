"""A deterministic Resource list answers only requests that a plain list can answer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.conversation.semantic_planning_models import SemanticOutputShape
from fdai.core.conversation.semantic_stated_list_scope import listing_answers_other_request
from fdai.core.conversation.semantic_target_candidate_planning import (
    build_stated_resource_filter_frame,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    load_inventory_query_language_from_mapping,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DESCRIPTORS: tuple[dict[str, Any], ...] = (
    {
        "kind": "object",
        "name": "Resource",
        "properties": {
            "name": {"readable": True},
            "type": {
                "readable": True,
                "value_groups": [
                    {
                        "id": "compute.vm-scale-set",
                        "terms": ["virtual machine scale set", "vmss"],
                        "values": ["compute.vm-scale-set"],
                    },
                    {
                        "id": "kubernetes-cluster",
                        "terms": ["aks", "kubernetes cluster"],
                        "values": ["kubernetes-cluster"],
                    },
                ],
            },
        },
    },
)


@pytest.fixture(scope="module")
def registry() -> InventoryQueryLanguageRegistry:
    path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml"
    return load_inventory_query_language_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def _judgment(*targets: dict[str, Any], facets: tuple[str, ...]) -> dict[str, Any]:
    return {
        "primary_intent": "query.contextual_resources",
        "requested_facets": facets,
        "targets": targets,
        "action_posture": "advise_only",
        "confidence": 0.9,
    }


@pytest.mark.parametrize(
    "utterance",
    ["aks-prod-01 시작해줘", "restart aks-prod-01", "aks-prod-01와 연결된 리소스 보여줘"],
)
def test_mutation_or_relationship_request_never_becomes_a_plain_list(
    utterance: str,
    registry: InventoryQueryLanguageRegistry,
) -> None:
    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {"kind": "resource_type_filter", "value": "aks-prod-01", "canonical_value": None},
            facets=("resource_collection", "list"),
        ),
        utterance=utterance,
        context=(),
        descriptors=_DESCRIPTORS,
        inventory_query_language=registry,
    )

    assert listing_answers_other_request(utterance, _DESCRIPTORS, registry=registry)
    assert result is None


def test_signal_term_inside_a_stated_type_states_only_the_type(
    registry: InventoryQueryLanguageRegistry,
) -> None:
    assert not listing_answers_other_request(
        "Show me all virtual machine scale sets",
        _DESCRIPTORS,
        registry=registry,
    )


def test_only_stated_name_fragment_builds_a_name_filtered_resource_list(
    registry: InventoryQueryLanguageRegistry,
) -> None:
    utterance = "이름에 bori가 들어간 리소스 찾아줘"

    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {"kind": "resource_name_filter", "value": "bori", "canonical_value": None},
            facets=("resource_collection", "list", "name_filter"),
        ),
        utterance=utterance,
        context=(),
        descriptors=_DESCRIPTORS,
        inventory_query_language=registry,
    )

    assert result is not None
    proposal, frame = result
    assert proposal.subject_constraints == ("Resource", "bori")
    assert frame.output_shape == SemanticOutputShape.PROPERTY_FILTERED_RESOURCES


def test_name_fragment_that_is_declared_vocabulary_builds_no_list(
    registry: InventoryQueryLanguageRegistry,
) -> None:
    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {"kind": "resource_name_filter", "value": "vmss", "canonical_value": None},
            facets=("resource_collection", "list", "name_filter"),
        ),
        utterance="vmss 찾아줘",
        context=(),
        descriptors=_DESCRIPTORS,
        inventory_query_language=registry,
    )

    assert result is None or result[0].subject_constraints != ("Resource", "vmss")


_STORAGE_DESCRIPTORS: tuple[dict[str, Any], ...] = (
    {
        "kind": "object",
        "name": "Resource",
        "properties": {
            "name": {"readable": True},
            "type": {
                "readable": True,
                "value_groups": [
                    {
                        "id": "object-storage",
                        "terms": ["storage account", "스토리지 계정"],
                        "values": ["object-storage"],
                    }
                ],
            },
        },
    },
)


@pytest.mark.parametrize(
    ("utterance", "region", "korean"),
    [
        ("koreacentral 리전에 있는 스토리지 계정 알려줘", "koreacentral", True),
        ("Show storage accounts in the westus2 region", "westus2", False),
    ],
)
def test_region_qualified_fragment_is_clarified_instead_of_matched_as_a_name(
    utterance: str,
    region: str,
    korean: bool,
    registry: InventoryQueryLanguageRegistry,
) -> None:
    type_text = "스토리지 계정" if korean else "storage accounts"
    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {"kind": "resource_type_filter", "value": type_text, "canonical_value": None},
            {"kind": "resource_name_filter", "value": region, "canonical_value": None},
            facets=("list",),
        ),
        utterance=utterance,
        context=(),
        descriptors=_STORAGE_DESCRIPTORS,
        inventory_query_language=registry,
    )

    assert result is not None
    proposal, frame = result
    assert proposal.unresolved_terms == ("location_filter",)
    assert proposal.clarification is not None and region in proposal.clarification
    assert ("지역 조건" in proposal.clarification) is korean
    assert frame.unresolved_terms


def test_unqualified_name_fragment_still_narrows_a_typed_list(
    registry: InventoryQueryLanguageRegistry,
) -> None:
    utterance = "fdai가 들어간 스토리지 계정 알려줘"
    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {"kind": "resource_type_filter", "value": "스토리지 계정", "canonical_value": None},
            {"kind": "resource_name_filter", "value": "fdai", "canonical_value": None},
            facets=("list",),
        ),
        utterance=utterance,
        context=(),
        descriptors=_STORAGE_DESCRIPTORS,
        inventory_query_language=registry,
    )

    assert result is not None
    assert result[0].subject_constraints == ("Resource", "fdai")
    assert result[0].unresolved_terms == ()


def test_request_facet_word_in_the_utterance_is_not_a_name_fragment(
    registry: InventoryQueryLanguageRegistry,
) -> None:
    descriptors: tuple[dict[str, Any], ...] = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "name": {"readable": True},
                "type": {
                    "readable": True,
                    "value_groups": [
                        {
                            "id": "container-registry",
                            "terms": ["container registry"],
                            "values": ["container-registry"],
                        }
                    ],
                },
            },
        },
    )
    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {
                "kind": "resource_type_filter",
                "value": "container registries",
                "canonical_value": None,
            },
            facets=("list",),
        ),
        utterance="List the container registries.",
        context=(),
        descriptors=descriptors,
        inventory_query_language=registry,
    )

    assert result is not None
    assert result[0].subject_constraints == ("Resource",)


def test_count_question_over_a_stated_type_builds_the_typed_list(
    registry: InventoryQueryLanguageRegistry,
) -> None:
    descriptors: tuple[dict[str, Any], ...] = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "name": {"readable": True},
                "type": {
                    "readable": True,
                    "value_groups": [
                        {
                            "id": "resource-group",
                            "terms": ["resource group", "리소스 그룹"],
                            "values": ["resource-group"],
                        }
                    ],
                },
            },
        },
    )
    result = build_stated_resource_filter_frame(
        semantic_judgment=_judgment(
            {"kind": "object_type", "value": "리소스 그룹", "canonical_value": "resource-group"},
            facets=("resource_collection", "list"),
        ),
        utterance="리소스 그룹이 몇 개야?",
        context=(),
        descriptors=descriptors,
        inventory_query_language=registry,
    )

    assert result is not None
    proposal, frame = result
    assert proposal.subject_constraints == ("Resource",)
    assert frame.output_shape == SemanticOutputShape.PROPERTY_FILTERED_RESOURCES
