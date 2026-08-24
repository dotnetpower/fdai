"""Validate semantic frame proposals before plan construction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation

from .semantic_current_state_planning import exact_target_from_constraints
from .semantic_planning_alignment import DECLARATION_SECTIONS_BY_MEASURE
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_value_filters

_SERVER_BOUND_REQUIREMENTS = frozenset(
    {ClarificationRequirement.PRINCIPAL_SCOPE, ClarificationRequirement.PURPOSE}
)
_SCHEMA_LEVEL_OUTPUT_SHAPES = frozenset(
    {"ontology_declaration", "ontology_manifest", "ontology_relationships"}
)
# Provider inventory names one concrete instance with joined segments
# (`aks-fdai-observe-lab`). A declaration name is dotted or a single word, and a
# two-segment token is a product word (`gpt-4o`), so neither shape matches.
_RUNTIME_INSTANCE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}(?![A-Za-z0-9_.-])"
)
_MAX_SCANNED_TOKENS = 32
_SPECIALIZED_OPERATIONS_BY_OUTPUT_SHAPE = {
    "contextual_resource_list": SemanticOperation.SELECT,
    "inventory_impact": SemanticOperation.SELECT,
    "resource_event_history": SemanticOperation.SELECT,
    "resource_health_list": SemanticOperation.SELECT,
    "resource_metric_list": SemanticOperation.SELECT,
    "resource_state_list": SemanticOperation.SELECT,
    "resource_target_candidates": SemanticOperation.SELECT,
    "subscription_service_health": SemanticOperation.SELECT,
    "target_activity": SemanticOperation.SELECT,
    "target_current_state": SemanticOperation.SELECT,
    "target_error_activity_correlation": SemanticOperation.COMPARE,
    "target_health_assessment": SemanticOperation.VALIDATE,
    "target_ingress_configuration": SemanticOperation.SELECT,
    "target_resource_metric": SemanticOperation.SELECT,
    "target_resource_metric_series": SemanticOperation.SELECT,
}
_SAFE_FRAME_REJECTION_REASONS = frozenset(
    {
        "causal investigation requires a diagnosis answer shape",
        "causal investigation requires an onset or change-point cue",
        "causal investigation requires support and refutation evidence",
        "explicit aggregation request requires aggregation_table output",
        "explicit impact request requires inventory_impact output",
        "explicit listing request cannot use aggregation_table output",
        "historical semantic request requires a temporal capability",
        "investigation entity ids MUST be unique",
        "investigation entity type is absent from the principal manifest",
        "investigation hypothesis competitors are invalid",
        "investigation hypothesis effect measure is unknown",
        "investigation hypothesis ids MUST be unique",
        "investigation hypothesis metric concept is unavailable",
        "investigation hypothesis relationship is unknown",
        "investigation intent MUST use explain_change",
        "investigation intent requires one affected target",
        "investigation measure ids MUST be unique",
        "investigation measure target is unknown",
        "investigation metric concept is unavailable",
        "investigation primary symptom measure is unknown",
        "investigation relationship endpoint is unknown",
        "investigation relationship ids MUST be unique",
        "investigation relationship side is absent from the manifest",
        "investigation relationship source type does not match",
        "investigation relationship target type does not match",
        "investigation source span does not match the utterance",
        "investigation utterance MUST be non-empty and bounded",
        "schema-level semantic frame names a runtime resource instance",
        "semantic aggregate operation requires aggregation_table output",
        "semantic clarification requests server-bound context",
        "semantic declaration frame requires an exact declaration measure",
        "semantic explain_change operation requires causal_evidence output",
        "semantic property-filter plan cannot use multiple existence-only predicates",
        "semantic Rule state frame requires the exact Rule declaration",
        "resource target candidates are server-owned",
        "specialized semantic output requires its fixed operation",
        "semantic validate operation requires evidence_validation output",
        "structured investigation intent requires semantic causal evidence",
        "target-bound causal evidence requires structured investigation intent",
    }
)


def _safe_frame_rejection_reason(exc: Exception) -> str:
    message = str(exc)
    if type(exc) is ValueError and message in _SAFE_FRAME_REJECTION_REASONS:
        return message
    return type(exc).__name__


def _validate_frame_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> None:
    _reject_server_owned_output_shape(proposal.output_shape)
    if _SERVER_BOUND_REQUIREMENTS.intersection(proposal.clarification_requirements):
        raise ValueError("semantic clarification requests server-bound context")
    is_evidence_validation = proposal.output_shape in {
        "evidence_validation",
        "target_health_assessment",
    }
    is_action_draft = proposal.output_shape is SemanticOutputShape.ACTION_DRAFT
    if (proposal.operation is SemanticOperation.ACTION_DRAFT) != is_action_draft:
        raise ValueError("semantic action_draft operation requires action_draft output")
    if (proposal.operation is SemanticOperation.VALIDATE) != is_evidence_validation:
        raise ValueError("semantic validate operation requires evidence_validation output")
    is_causal_evidence = proposal.output_shape == "causal_evidence"
    if (proposal.operation is SemanticOperation.EXPLAIN_CHANGE) != is_causal_evidence:
        raise ValueError("semantic explain_change operation requires causal_evidence output")
    is_aggregation = proposal.output_shape == "aggregation_table"
    if (proposal.operation is SemanticOperation.AGGREGATE) != is_aggregation:
        raise ValueError("semantic aggregate operation requires aggregation_table output")
    specialized_operation = _SPECIALIZED_OPERATIONS_BY_OUTPUT_SHAPE.get(proposal.output_shape)
    if specialized_operation is not None and proposal.operation is not specialized_operation:
        raise ValueError("specialized semantic output requires its fixed operation")
    if proposal.investigation is not None and not is_causal_evidence:
        raise ValueError("structured investigation intent requires semantic causal evidence")
    if (
        is_causal_evidence
        and proposal.investigation is None
        and _has_target_bound_subject(proposal, descriptors=descriptors)
        and not _is_resource_candidate_request(
            proposal,
            utterance=utterance,
            descriptors=descriptors,
        )
    ):
        raise ValueError("target-bound causal evidence requires structured investigation intent")
    if (
        proposal.output_shape in _SCHEMA_LEVEL_OUTPUT_SHAPES
        and not _is_complete_ontology_trace_proposal(proposal)
        and _names_runtime_instance(
            (utterance, *proposal.subject_constraints),
            descriptors=descriptors,
        )
    ):
        raise ValueError("schema-level semantic frame names a runtime resource instance")
    if proposal.temporal_scope and proposal.output_shape in {
        SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST,
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
        SemanticOutputShape.RESOURCE_STATE_LIST,
        SemanticOutputShape.TARGET_CURRENT_STATE,
        SemanticOutputShape.TARGET_INGRESS_CONFIGURATION,
    }:
        raise ValueError("historical semantic request requires a temporal capability")
    if proposal.output_shape == "ontology_declaration":
        measures = frozenset(proposal.measure_concepts)
        if (
            proposal.operation is not SemanticOperation.SELECT
            or len(proposal.subject_constraints) != 1
            or not measures
            or not measures <= DECLARATION_SECTIONS_BY_MEASURE.keys()
        ):
            raise ValueError("semantic declaration frame requires an exact declaration measure")
        if "rule_state" in measures and (
            measures != {"rule_state"} or proposal.subject_constraints != ("Rule",)
        ):
            raise ValueError("semantic Rule state frame requires the exact Rule declaration")


def _reject_server_owned_output_shape(output_shape: SemanticOutputShape) -> None:
    if output_shape is SemanticOutputShape.RESOURCE_TARGET_CANDIDATES:
        raise ValueError("resource target candidates are server-owned")


def _names_runtime_instance(
    texts: tuple[str, ...],
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    """Report whether any text names a concrete resource the schema cannot hold.

    Every proposal stage below the frame is checked against the frame, so a
    frame that answers a different question than the operator asked produces a
    plan, a result, and an answer that all agree with each other and with
    nothing else. A schema family reads declarations, so an identifier-shaped
    token that matches no declared name, property, or value is evidence the
    frame left the question behind.
    """
    candidates = [
        match.group(0) for text in texts for match in _RUNTIME_INSTANCE_TOKEN.finditer(text)
    ][:_MAX_SCANNED_TOKENS]
    if not candidates:
        return False
    declared = _declared_vocabulary(descriptors)
    return any(candidate.casefold() not in declared for candidate in candidates)


def _is_complete_ontology_trace_proposal(proposal: SemanticFrameProposal) -> bool:
    required_measures = {
        "action_type",
        "resource_type",
        "signal_type",
    }
    return (
        proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape is SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and set(proposal.subject_constraints)
        == {"ActionType", "ResourceType", "Rule", "SignalType"}
        and required_measures <= set(proposal.measure_concepts)
        and bool({"trace", "trace_relationships"}.intersection(proposal.measure_concepts))
        and bool(
            {
                "no_current_finding",
                "without_asserting_current_finding",
                "without_current_finding",
            }.intersection(proposal.measure_concepts)
        )
        and not proposal.temporal_scope
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
        and proposal.clarification is None
        and proposal.investigation is None
    )


def _has_target_bound_subject(
    proposal: SemanticFrameProposal,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    declared_subjects = {
        name.casefold()
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    return any(
        subject.casefold() not in declared_subjects for subject in proposal.subject_constraints
    )


def _is_resource_candidate_request(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    """Recognize a typed Resource category that still lacks one exact identity."""

    filters = stated_value_filters(utterance, descriptors)
    return bool(filters.get(("Resource", "type"))) and (
        exact_target_from_constraints(
            proposal.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is None
    )


def _declared_vocabulary(descriptors: tuple[dict[str, Any], ...]) -> frozenset[str]:
    """Collect every word the supplied release lets a schema question name."""
    words: set[str] = set()
    for descriptor in descriptors:
        name = descriptor.get("name")
        if isinstance(name, str):
            words.add(name.casefold())
        properties = descriptor.get("properties")
        if isinstance(properties, Mapping):
            for property_name, facet in properties.items():
                if isinstance(property_name, str):
                    words.add(property_name.casefold())
                words.update(_declared_facet_words(facet))
        elif isinstance(properties, list):
            words.update(item.casefold() for item in properties if isinstance(item, str))
    return frozenset(words)


def _declared_facet_words(facet: object) -> set[str]:
    """Return the declared values and request terms of one property facet."""
    if not isinstance(facet, Mapping):
        return set()
    words = {value.casefold() for value in _string_list(facet.get("values"))}
    groups = facet.get("value_groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            group_id = group.get("id")
            if isinstance(group_id, str):
                words.add(group_id.casefold())
            words.update(value.casefold() for value in _string_list(group.get("values")))
            words.update(term.casefold() for term in _string_list(group.get("terms")))
    return words


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


__all__ = [
    "_declared_facet_words",
    "_declared_vocabulary",
    "_has_target_bound_subject",
    "_is_complete_ontology_trace_proposal",
    "_is_resource_candidate_request",
    "_names_runtime_instance",
    "_reject_server_owned_output_shape",
    "_safe_frame_rejection_reason",
    "_string_list",
    "_validate_frame_proposal",
]
