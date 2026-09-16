"""Compile exact logical-service state reads across runtime resource forms."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_OBSERVED_CONCEPT,
)

from .semantic_planning_models import SemanticOutputShape

_TARGET_TYPE_PREFIX = "OperatingTarget.type="
_TARGET_VALUE_PREFIX = "OperatingTarget.value="
_SERVICE_TO_WORKLOAD = "implemented_by"
_WORKLOAD_TO_RESOURCE = "workload_runs_on"


def compile_logical_service_current_state_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build one exact service read or return no plan for another frame family."""

    if frame.output_shape != SemanticOutputShape.LOGICAL_SERVICE_CURRENT_STATE:
        return None
    target = _operating_target(frame, utterance=utterance)
    if target is None or not _has_runtime_path(manifest.descriptors):
        return None
    target_type, target_value = target
    target_properties = _object_properties(manifest.descriptors, target_type)
    if not {"id", "name"} <= target_properties or not _has_state_function(manifest.descriptors):
        return None
    as_of = evaluation_time.astimezone(UTC)
    target_nodes = tuple(
        _object_set_node(
            f"logical-service-target-by-{property_name}",
            object_type=target_type,
            predicate=ObjectPredicate(property=property_name, equals=target_value),
            as_of=as_of,
            purpose=purpose,
            limit=2,
        )
        for property_name in ("id", "name")
    )
    if "aliases" in target_properties:
        target_nodes = (
            *target_nodes,
            _object_set_node(
                "logical-service-target-by-alias",
                object_type=target_type,
                predicate=ObjectPredicate(
                    property="aliases",
                    operator=ObjectPredicateOperator.CONTAINS,
                    equals=target_value,
                ),
                as_of=as_of,
                purpose=purpose,
                limit=2,
            ),
        )
    resolved_target = _node(
        "logical-service-target",
        QueryNodeKind.UNION,
        depends_on=tuple(node.node_id for node in target_nodes),
        output_kind="query.table",
    )
    resource_steps: tuple[dict[str, object], ...]
    if target_type == "BusinessService":
        services = resolved_target
        workloads = _typed_path_node(
            "logical-service-workloads",
            depends_on=resolved_target.node_id,
            steps=(_path_step(_SERVICE_TO_WORKLOAD, "Workload"),),
            as_of=as_of,
            purpose=purpose,
        )
        resource_steps = (
            _path_step(_SERVICE_TO_WORKLOAD, "Workload"),
            _path_step(_WORKLOAD_TO_RESOURCE, "Resource"),
        )
    else:
        services = _typed_path_node(
            "logical-business-services",
            depends_on=resolved_target.node_id,
            steps=(_path_step(_SERVICE_TO_WORKLOAD, "BusinessService", direction="incoming"),),
            as_of=as_of,
            purpose=purpose,
        )
        workloads = resolved_target
        resource_steps = (_path_step(_WORKLOAD_TO_RESOURCE, "Resource"),)
    resources = _typed_path_node(
        "logical-service-resources",
        depends_on=resolved_target.node_id,
        steps=resource_steps,
        as_of=as_of,
        purpose=purpose,
    )
    states = _node(
        "logical-service-resource-states",
        QueryNodeKind.FUNCTION,
        depends_on=(resources.node_id,),
        arguments={
            "function_name": RESOURCE_STATE_FUNCTION_NAME,
            "arguments": {"state_concepts": [RESOURCE_STATE_OBSERVED_CONCEPT]},
            "dependency_arguments": {resources.node_id: "query_result"},
        },
        output_kind="query.table",
    )
    nodes = (
        *target_nodes,
        resolved_target,
        *(node for node in (services, workloads) if node is not resolved_target),
        resources,
        states,
    )
    output_node_ids = (
        services.node_id,
        workloads.node_id,
        resources.node_id,
        states.node_id,
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": list(output_node_ids),
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=output_node_ids,
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _operating_target(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
) -> tuple[str, str] | None:
    types = tuple(
        constraint.removeprefix(_TARGET_TYPE_PREFIX)
        for constraint in frame.subject_constraints
        if constraint.startswith(_TARGET_TYPE_PREFIX)
    )
    values = tuple(
        constraint.removeprefix(_TARGET_VALUE_PREFIX)
        for constraint in frame.subject_constraints
        if constraint.startswith(_TARGET_VALUE_PREFIX)
    )
    if (
        len(types) != 1
        or types[0] not in {"BusinessService", "Workload"}
        or len(values) != 1
        or not values[0]
        or utterance.count(values[0]) != 1
    ):
        return None
    return types[0], values[0]


def _object_properties(
    descriptors: tuple[dict[str, Any], ...],
    object_type: str,
) -> frozenset[str]:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and descriptor.get("name") == object_type
    )
    if len(selected) != 1 or not isinstance(selected[0].get("properties"), Mapping):
        return frozenset()
    return frozenset(str(name) for name in selected[0]["properties"])


def _has_runtime_path(descriptors: tuple[dict[str, Any], ...]) -> bool:
    declared = {
        (descriptor.get("name"), descriptor.get("from_type"), descriptor.get("to_type"))
        for descriptor in descriptors
        if descriptor.get("kind") == "link"
    }
    return {
        (_SERVICE_TO_WORKLOAD, "BusinessService", "Workload"),
        (_WORKLOAD_TO_RESOURCE, "Workload", "Resource"),
    } <= declared


def _has_state_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_STATE_FUNCTION_NAME
        for descriptor in descriptors
    )


def _object_set_node(
    node_id: str,
    *,
    object_type: str,
    predicate: ObjectPredicate,
    as_of: datetime,
    purpose: str,
    limit: int,
) -> OntologyQueryNode:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=object_type),
        predicates=(predicate,),
        as_of=as_of,
        purpose=purpose,
        limit=limit,
        include_relationships=False,
    )
    return _node(
        node_id,
        QueryNodeKind.OBJECT_SET,
        arguments={"definition": definition.model_dump(mode="json")},
        output_kind="query.table",
    )


def _typed_path_node(
    node_id: str,
    *,
    depends_on: str,
    steps: tuple[dict[str, object], ...],
    as_of: datetime,
    purpose: str,
) -> OntologyQueryNode:
    return _node(
        node_id,
        QueryNodeKind.TYPED_PATH,
        depends_on=(depends_on,),
        arguments={
            "steps": list(steps),
            "as_of": as_of.isoformat(),
            "purpose": purpose,
            "limit": 100,
        },
        output_kind="query.table",
    )


def _path_step(
    link_type: str,
    object_type: str,
    *,
    direction: str = "outgoing",
) -> dict[str, object]:
    return {
        "link_type": link_type,
        "direction": direction,
        "selector": {"kind": "object_type", "name": object_type},
        "max_hops": 1,
    }


def _node(
    node_id: str,
    kind: QueryNodeKind,
    *,
    depends_on: tuple[str, ...] = (),
    arguments: dict[str, object] | None = None,
    output_kind: str,
) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id=node_id,
        kind=kind,
        depends_on=depends_on,
        arguments_json=canonical_json(arguments or {}),
        output_kind=output_kind,
    )


__all__ = ["compile_logical_service_current_state_plan"]
