"""Verify that a semantic query plan preserves its accepted problem frame."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)

from .semantic_planning_frame import CHANGE_ACTIVITY_COMPARISON_MEASURE

_SPECIALIZED_FUNCTIONS_BY_OUTPUT_SHAPE = {
    "contextual_resource_list": frozenset({"query.contextual_resources"}),
    "incident_evidence": frozenset({"query.incident_evidence"}),
    "inventory_impact": frozenset({"query.inventory_impact"}),
    "ontology_declaration": frozenset({"query.ontology_declaration"}),
    "ontology_manifest": frozenset({"query.manifest"}),
    "ontology_relationships": frozenset({"query.ontology_relationships"}),
    "ontology_release_evidence_health": frozenset(
        {"query.ontology_evidence_health", "query.ontology_release_diff"}
    ),
    "resource_event_history": frozenset({"query.resource_event_history"}),
    "resource_condition_sections": frozenset(
        {"query.resource_health_inventory", "query.resource_state_inventory"}
    ),
    "resource_health_list": frozenset({"query.resource_health_inventory"}),
    "resource_metric_list": frozenset({"query.resource_metric_inventory"}),
    "resource_state_list": frozenset({"query.resource_state_inventory"}),
    "resource_state_transitions": frozenset({"query.resource_state_transitions"}),
    "subscription_scope_identity": frozenset({"query.subscription_scope_identity"}),
    "subscription_service_health": frozenset({"query.subscription_service_health"}),
    "target_activity": frozenset({"query.resource_activity"}),
    "target_current_state": frozenset({"query.resource_current_state"}),
    "target_error_activity_correlation": frozenset({"query.resource_error_activity_correlation"}),
    "target_health_assessment": frozenset({"query.target_health_assessment"}),
    "target_ingress_configuration": frozenset({"query.resource_ingress_configuration"}),
    "target_resource_metric": frozenset({"query.resource_metric_inventory"}),
    "target_resource_metric_series": frozenset({"query.resource_metric_series"}),
}
_SPECIALIZED_FUNCTION_OUTPUT_SHAPES = {
    function_name: output_shape
    for output_shape, function_names in _SPECIALIZED_FUNCTIONS_BY_OUTPUT_SHAPE.items()
    for function_name in function_names
}
_DECLARATION_KINDS = frozenset({"action", "function", "interface", "link", "object"})
DECLARATION_SECTIONS_BY_MEASURE = {
    "declaration_detail": "detail",
    "declaration_dependents": "dependents",
    "rule_state": "detail",
}
_REQUIRED_NODE_KINDS_BY_OUTPUT_SHAPE = {
    "aggregation_table": frozenset({QueryNodeKind.AGGREGATE}),
    "causal_evidence": frozenset({QueryNodeKind.EVIDENCE_JOIN}),
    "evidence_validation": frozenset({QueryNodeKind.OBJECT_SET}),
    "property_filtered_resources": frozenset({QueryNodeKind.OBJECT_SET}),
    "resource_state_list": frozenset({QueryNodeKind.FUNCTION}),
    "resource_state_transitions": frozenset({QueryNodeKind.FUNCTION}),
    "resource_condition_sections": frozenset({QueryNodeKind.FUNCTION}),
    "resource_target_candidates": frozenset({QueryNodeKind.OBJECT_SET}),
    "subscription_scope_identity": frozenset({QueryNodeKind.FUNCTION}),
    "subscription_service_health": frozenset({QueryNodeKind.FUNCTION}),
    "target_resource_metric_series": frozenset({QueryNodeKind.FUNCTION}),
    "temporal_comparison": frozenset(
        {
            QueryNodeKind.EVIDENCE_JOIN,
            QueryNodeKind.METRIC_SCOPE_SERIES,
            QueryNodeKind.METRIC_SERIES,
            QueryNodeKind.TOPOLOGY_DIFF,
        }
    ),
    "topology_graph": frozenset({QueryNodeKind.TOPOLOGY_AT}),
}


def verify_frame_plan_alignment(
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    *,
    descriptors: tuple[dict[str, Any], ...],
    allow_bound_contextual: bool = False,
) -> None:
    """Reject a verified plan that selects capabilities outside its accepted frame."""
    selected_node_kinds = {node.kind for node in plan.nodes}
    if frame.output_shape == "contextual_resource_list" and not allow_bound_contextual:
        raise ValueError("contextual specialized functions require the bound-context output plan")
    if (QueryNodeKind.AGGREGATE in selected_node_kinds) != (
        frame.operation is SemanticOperation.AGGREGATE
    ):
        raise ValueError("semantic aggregate plan must match the frame operation")
    required_node_kinds = _REQUIRED_NODE_KINDS_BY_OUTPUT_SHAPE.get(frame.output_shape)
    if required_node_kinds is not None and required_node_kinds.isdisjoint(selected_node_kinds):
        raise ValueError("semantic plan does not satisfy frame capability")
    if frame.output_shape == "property_filtered_resources" and not any(
        _object_set_has_predicates(node.arguments_json)
        for node in plan.nodes
        if node.kind is QueryNodeKind.OBJECT_SET
    ):
        raise ValueError("semantic property-filter plan requires a predicate")
    if frame.output_shape == "property_filtered_resources" and any(
        _object_set_has_multiple_existence_only_predicates(node.arguments_json)
        for node in plan.nodes
        if node.kind is QueryNodeKind.OBJECT_SET
    ):
        raise ValueError(
            "semantic property-filter plan cannot use multiple existence-only predicates"
        )
    _verify_current_relationship_mapping(frame, plan, descriptors=descriptors)
    _verify_manifest_aggregate_source(frame, plan)

    output_node_ids = set(plan.output_node_ids)
    selected_functions: set[str] = set()
    selected_output_functions: set[str] = set()
    for node in plan.nodes:
        if node.kind is not QueryNodeKind.FUNCTION:
            continue
        arguments = json.loads(node.arguments_json)
        function_name = arguments.get("function_name") if isinstance(arguments, Mapping) else None
        if isinstance(function_name, str):
            selected_functions.add(function_name)
            if node.node_id in output_node_ids:
                selected_output_functions.add(function_name)

    if (
        CHANGE_ACTIVITY_COMPARISON_MEASURE in frame.measure_concepts
        and not {
            "query.ontology_relationships",
            "query.resource_change_activity",
        }
        <= selected_functions
    ):
        raise ValueError(
            "semantic change comparison requires exact activity and relationship reads"
        )

    expected_functions = _SPECIALIZED_FUNCTIONS_BY_OUTPUT_SHAPE.get(frame.output_shape)
    if expected_functions is not None and not expected_functions <= selected_output_functions:
        raise ValueError("semantic plan does not satisfy specialized frame output")
    if any(
        not _function_matches_output_shape(function_name, frame.output_shape)
        for function_name in selected_output_functions
        if function_name in _SPECIALIZED_FUNCTION_OUTPUT_SHAPES
    ):
        raise ValueError("semantic plan selects a function outside the frame output")
    _verify_ontology_declaration_subject(frame, plan, descriptors=descriptors)


def _function_matches_output_shape(function_name: str, output_shape: str) -> bool:
    expected = _SPECIALIZED_FUNCTION_OUTPUT_SHAPES[function_name]
    if output_shape == expected:
        return True
    return output_shape == "resource_condition_sections" and function_name in {
        "query.resource_health_inventory",
        "query.resource_state_inventory",
    }


def _verify_current_relationship_mapping(
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> None:
    """Require current endpoint instances beside their declared relationship."""

    if frame.output_shape != "ontology_relationships" or frame.temporal_scope != {
        "kind": "current"
    }:
        return
    requested_types = {
        constraint
        for constraint in frame.subject_constraints
        if any(
            descriptor.get("kind") == "object" and descriptor.get("name") == constraint
            for descriptor in descriptors
        )
    }
    output_node_ids = set(plan.output_node_ids)
    selected_types = {
        selector_name
        for node in plan.nodes
        if node.kind is QueryNodeKind.OBJECT_SET and node.node_id in output_node_ids
        if (selector_name := _object_set_selector_name(node.arguments_json)) is not None
    }
    if not requested_types or not requested_types <= selected_types:
        raise ValueError("semantic current relationship plan requires endpoint ObjectSets")


def _verify_manifest_aggregate_source(
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
) -> None:
    """Allow manifest aggregation only for the declaration kinds the frame requests."""
    if frame.output_shape != "aggregation_table":
        return
    manifest_kinds = tuple(
        kinds
        for node in plan.nodes
        if node.kind is QueryNodeKind.FUNCTION
        if (kinds := _manifest_query_kinds(node.arguments_json)) is not None
    )
    if not manifest_kinds:
        return
    requested_kinds = frozenset(frame.subject_constraints)
    if not requested_kinds or not requested_kinds.issubset(_DECLARATION_KINDS):
        raise ValueError("semantic manifest aggregate requires declaration subjects")
    if any(kinds != requested_kinds for kinds in manifest_kinds):
        raise ValueError("semantic manifest aggregate kinds differ from frame subjects")


def _verify_ontology_declaration_subject(
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> None:
    """Bind declaration function arguments to one exact frame intent."""
    if frame.output_shape != "ontology_declaration":
        return
    if len(frame.subject_constraints) != 1:
        raise ValueError("semantic declaration frame requires one exact subject")
    expected_name = frame.subject_constraints[0]
    expected_sections = frozenset(
        DECLARATION_SECTIONS_BY_MEASURE[item] for item in frame.measure_concepts
    )
    expected_kinds = frozenset(
        kind
        for descriptor in descriptors
        if descriptor.get("name") == expected_name
        if isinstance((kind := descriptor.get("kind")), str)
        if kind in {"action", "link", "object"}
    )
    selected = tuple(
        (node.node_id, node.output_kind, function_arguments)
        for node in plan.nodes
        if node.kind is QueryNodeKind.FUNCTION
        if (function_arguments := _function_arguments(node.arguments_json)) is not None
    )
    if len(selected) != len(expected_sections):
        raise ValueError("semantic declaration plan sections differ from frame")
    if len(selected) != len(plan.nodes):
        raise ValueError("semantic declaration plan contains unrelated nodes")
    if {node_id for node_id, _output_kind, _arguments in selected} != set(plan.output_node_ids):
        raise ValueError("semantic declaration plan outputs differ from requested sections")
    if any(output_kind != "query.table" for _node_id, output_kind, _arguments in selected):
        raise ValueError("semantic declaration plan output kind differs from function contract")
    if any(
        arguments.get("name") != expected_name for _node_id, _output_kind, arguments in selected
    ):
        raise ValueError("semantic declaration plan subject differs from frame")
    if {
        arguments.get("section") for _node_id, _output_kind, arguments in selected
    } != expected_sections:
        raise ValueError("semantic declaration plan sections differ from frame")
    if len(expected_kinds) != 1 or any(
        arguments.get("kind") not in expected_kinds
        for _node_id, _output_kind, arguments in selected
    ):
        raise ValueError("semantic declaration plan kind differs from manifest")


def _function_arguments(arguments_json: str) -> Mapping[str, object] | None:
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, Mapping):
        return None
    if arguments.get("function_name") != "query.ontology_declaration":
        return None
    function_arguments = arguments.get("arguments")
    return function_arguments if isinstance(function_arguments, Mapping) else None


def _manifest_query_kinds(arguments_json: str) -> frozenset[str] | None:
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, Mapping) or arguments.get("function_name") != "query.manifest":
        return None
    function_arguments = arguments.get("arguments")
    kinds = function_arguments.get("kinds") if isinstance(function_arguments, Mapping) else None
    if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds):
        return frozenset()
    return frozenset(kinds)


def _object_set_has_predicates(arguments_json: str) -> bool:
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, Mapping):
        return False
    definition = arguments.get("definition")
    return isinstance(definition, Mapping) and bool(definition.get("predicates"))


def _object_set_selector_name(arguments_json: str) -> str | None:
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, Mapping):
        return None
    definition = arguments.get("definition")
    selector = definition.get("selector") if isinstance(definition, Mapping) else None
    if not isinstance(selector, Mapping) or selector.get("kind") != "object_type":
        return None
    name = selector.get("name")
    return name if isinstance(name, str) else None


def _object_set_has_multiple_existence_only_predicates(arguments_json: str) -> bool:
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, Mapping):
        return False
    definition = arguments.get("definition")
    predicates = definition.get("predicates") if isinstance(definition, Mapping) else None
    return (
        isinstance(predicates, list)
        and len(predicates) > 1
        and all(
            isinstance(predicate, Mapping) and predicate.get("operator") == "exists"
            for predicate in predicates
        )
    )


__all__ = ["DECLARATION_SECTIONS_BY_MEASURE", "verify_frame_plan_alignment"]
