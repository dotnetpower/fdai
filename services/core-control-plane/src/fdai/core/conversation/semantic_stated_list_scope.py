"""Keep a deterministic Resource list to requests that a plain list can answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame

from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryTargetCardinality,
    query_target_cardinality,
    query_term_spans,
)

from .semantic_planning_frame import build_semantic_frame
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_subject_fragment, stated_value_term_spans
from .semantic_target_candidate_constants import COLLECTION_FILTER_KINDS

# Characters allowed between a location term and the region value it qualifies.
_LOCATION_QUALIFIER_GAP = 3
# Machine request facets name an output shape, never a Resource name fragment, even when the
# operator's own word, such as "List", matches one.
_REQUEST_FACET_TOKENS = frozenset(
    {
        "count",
        "current_state",
        "details",
        "list",
        "name",
        "name_filter",
        "names",
        "resource_collection",
        "resource_count",
        "status",
        "summary",
        "type",
        "types",
    }
)


def collection_requested(
    utterance: str,
    registry: InventoryQueryLanguageRegistry | None,
) -> bool:
    """Return whether the turn asks about a collection, including a reviewed count request."""

    return query_target_cardinality(
        utterance, registry
    ) is QueryTargetCardinality.COLLECTION or bool(
        query_term_spans(utterance, registry, query_kind="count")
    )


def listing_answers_other_request(
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
    *,
    registry: InventoryQueryLanguageRegistry | None,
) -> bool:
    """Return whether a stated mutation or relationship request would become a plain list.

    Reviewed catalog signals state the request kind. A signal term inside a stated resource
    type term, such as `scale` in `virtual machine scale sets`, states only that type.
    """

    type_spans = stated_value_term_spans(utterance, descriptors)
    request_spans = (
        *query_term_spans(utterance, registry, signal="mutation"),
        *query_term_spans(utterance, registry, query_kind="relationships"),
    )
    return any(
        not any(outer_start <= start and end <= outer_end for outer_start, outer_end in type_spans)
        for start, end in request_spans
    )


def stated_name_fragment_frame(
    semantic_judgment: Mapping[str, Any],
    typed_targets: Sequence[Mapping[str, Any]],
    raw_facets: Sequence[str],
    filters: Mapping[tuple[str, str], tuple[str, ...]],
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a Resource name-fragment list when that verbatim fragment is the only filter."""

    if filters.get(("Resource", "type")) or len(typed_targets) != 1:
        return None
    target = typed_targets[0]
    value = target.get("value")
    if (
        target.get("kind") != "resource_name_filter"
        or not isinstance(value, str)
        or target.get("canonical_value") is not None
        or not {"list", "name_filter", "resource_collection"} & set(raw_facets)
        or utterance.casefold().count(value.casefold()) != 1
    ):
        return None
    fragment = stated_subject_fragment(utterance, ("Resource", value), descriptors)
    if fragment is None:
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource", fragment),
        measure_concepts=("name", "type"),
        temporal_scope={},
        output_shape=SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        evidence_requirements=("authoritative_inventory",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=float(semantic_judgment.get("confidence", 0.0)),
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def typed_resource_list_frame(
    semantic_judgment: Mapping[str, Any],
    typed_targets: Sequence[Mapping[str, Any]],
    raw_facets: Sequence[str],
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    registry: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build the typed Resource list, narrowed by at most one verbatim free-text fragment.

    A fragment the operator qualified as a region or location is not a name fragment. The
    ObjectSet contract cannot filter by location yet, so the request is clarified instead of
    reporting a verified empty name match.
    """

    target_values = [
        target["value"]
        for target in typed_targets
        if isinstance(target.get("kind"), str)
        and (
            target["kind"] == "affected_target"
            or (
                target["kind"] == "resource_group"
                and {"resource_collection", "list", "name_filter"} <= set(raw_facets)
            )
            or (
                target["kind"].endswith("_filter") and target["kind"] not in COLLECTION_FILTER_KINDS
            )
        )
        and isinstance(target.get("value"), str)
        and target.get("canonical_value") is None
    ]
    unique_target_values = tuple(
        dict.fromkeys(
            value
            for value in target_values
            if utterance.casefold().count(value.casefold()) == 1
            and stated_subject_fragment(utterance, (value,), descriptors) is not None
        )
    )
    fragment = (
        unique_target_values[0]
        if len(unique_target_values) == 1
        else stated_subject_fragment(
            utterance,
            tuple(facet for facet in raw_facets if facet not in _REQUEST_FACET_TOKENS),
            descriptors,
        )
    )
    if fragment is None and "name_filter" in raw_facets:
        return None
    if fragment is not None and _location_qualified(fragment, utterance, registry):
        return _location_filter_clarification(semantic_judgment, fragment, utterance, context)
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",) if fragment is None else ("Resource", fragment),
        measure_concepts=("name", "type"),
        temporal_scope={},
        output_shape=SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        evidence_requirements=("authoritative_inventory",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=float(semantic_judgment.get("confidence", 0.0)),
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _location_qualified(
    fragment: str,
    utterance: str,
    registry: InventoryQueryLanguageRegistry | None,
) -> bool:
    start = utterance.casefold().find(fragment.casefold())
    if start < 0:
        return False
    end = start + len(fragment)
    return any(
        0 <= span_start - end <= _LOCATION_QUALIFIER_GAP
        or 0 <= start - span_end <= _LOCATION_QUALIFIER_GAP
        for span_start, span_end in query_term_spans(
            utterance, registry, signal="location_reference"
        )
    )


def _location_filter_clarification(
    semantic_judgment: Mapping[str, Any],
    fragment: str,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    korean = any("가" <= character <= "힣" for character in utterance)
    safe = fragment.replace("`", "'")[:64]
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope={},
        output_shape=SemanticOutputShape.RESOURCE_LIST,
        evidence_requirements=(),
        unresolved_terms=("location_filter",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            f"지역 조건 `{safe}`은 아직 조회 필터로 적용할 수 없습니다. "
            "지역 조건 없이 전체 목록을 볼까요?"
            if korean
            else f"The region condition `{safe}` cannot be applied as a query filter yet. "
            "Do you want the full list without it?"
        ),
        investigation=None,
        confidence=float(semantic_judgment.get("confidence", 0.0)),
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def resource_filter_meaning_clarification(
    semantic_judgment: Mapping[str, Any],
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Ask which filter kind an unbound resource-type phrase means, in the operator's language."""

    korean = any("가" <= character <= "힣" for character in utterance)
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope={},
        output_shape=SemanticOutputShape.RESOURCE_LIST,
        evidence_requirements=(),
        unresolved_terms=("resource_filter_meaning",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "요청한 리소스 범위가 유형, 이름 포함, 또는 관계 기준인지 알려주세요?"
            if korean
            else "Should the resource scope use a type, a name fragment, or a relationship?"
        ),
        investigation=None,
        confidence=float(semantic_judgment.get("confidence", 0.0)),
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


__all__ = [
    "collection_requested",
    "listing_answers_other_request",
    "resource_filter_meaning_clarification",
    "stated_name_fragment_frame",
    "typed_resource_list_frame",
]
