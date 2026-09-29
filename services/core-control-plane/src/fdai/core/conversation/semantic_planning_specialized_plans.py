"""Server-owned specialized plan builders for semantic planning."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    INCIDENT_EVIDENCE_MAX_RECORDS,
)

from .semantic_planning_models import (
    BoundIncident,
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticOutputShape,
)
from .semantic_planning_support import _build_plan
from .semantic_planning_value_filters import (
    ground_stated_value_filters,
    stated_subject_fragment,
    stated_value_filters,
)
from .semantic_reasoning_form import (
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
)
from .semantic_reasoning_relations import select_relation_sides
from .semantic_resource_visibility import OPERATIONAL_RESOURCE_EXCLUDED_TYPES
from .session import Principal

_INCIDENT_EVIDENCE_NODE_ID = "bound_incident_evidence"
_GROUP_ANCHOR_NODE_ID = "stated-group-anchor"
_GROUP_MEMBERS_NODE_ID = "stated-group-members"
_RESOURCE_OBJECT_TYPE = "Resource"
_RESOURCE_GROUP_TYPE = "resource-group"


def build_inventory_document_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Read the secured inventory once; exhaustion remains an incomplete source."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_LIST
        or frame.subject_constraints != ("Resource",)
        or set(frame.measure_concepts) != {"complete_content", "download"}
        or frame.temporal_scope
        or frame.unresolved_terms
    ):
        return None
    proposal = QueryPlanProposal(
        nodes=(
            QueryNodeProposal(
                node_id="inventory-document",
                kind=QueryNodeKind.OBJECT_SET,
                arguments={
                    "definition": {
                        "selector": {"kind": "object_type", "name": "Resource"},
                        "as_of": evaluation_time.astimezone(UTC).isoformat(),
                        "purpose": purpose,
                        "include_relationships": False,
                        "limit": 1000,
                    }
                },
                output_kind="query.table",
            ),
        ),
        output_node_ids=("inventory-document",),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    verifier.verify(plan, manifest=manifest)
    return plan


def build_anchored_incident_plan(
    *,
    verifier: OntologyQueryPlanVerifier,
    bound_incident: BoundIncident | None,
    frame: SemanticProblemFrame,
    descriptors: tuple[dict[str, Any], ...],
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Build the anchored incident read from the binding, never from a proposal."""

    if bound_incident is None or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE:
        return None
    if not any(
        item.get("kind") == "function" and item.get("name") == INCIDENT_EVIDENCE_FUNCTION_NAME
        for item in descriptors
    ):
        return None
    proposal = QueryPlanProposal(
        nodes=(
            QueryNodeProposal(
                node_id=_INCIDENT_EVIDENCE_NODE_ID,
                kind=QueryNodeKind.FUNCTION,
                depends_on=(),
                arguments={
                    "function_name": INCIDENT_EVIDENCE_FUNCTION_NAME,
                    "arguments": {
                        "incident_id": bound_incident.incident_id,
                        "correlation_id": bound_incident.correlation_id,
                        "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
                    },
                    "dependency_arguments": {},
                },
                output_kind="query.value",
            ),
        ),
        output_node_ids=(_INCIDENT_EVIDENCE_NODE_ID,),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    verifier.verify(plan, manifest=manifest)
    return plan


def build_stated_value_filter_plan(
    *,
    verifier: OntologyQueryPlanVerifier,
    frame: SemanticProblemFrame,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Build a model-free ObjectSet for an explicit catalog value filter."""

    if frame.operation is not SemanticOperation.SELECT or frame.output_shape not in {
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
    }:
        return None
    allowed_properties = frozenset({"parent_id"}) if "parent_id" in frame.measure_concepts else None
    filters = stated_value_filters(
        utterance,
        descriptors,
        allowed_properties=allowed_properties,
    )
    object_types = {object_type for object_type, _property_name in filters}
    declared_object_types = {
        str(descriptor["name"])
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        and descriptor.get("name") in frame.subject_constraints
    }
    object_types.update(declared_object_types)
    if len(object_types) != 1:
        return None
    object_type = next(iter(object_types))
    membership = allowed_properties == frozenset({"parent_id"})
    # A membership frame carries its group first; member subtype phrases never compete with it.
    subject_fragment = stated_subject_fragment(
        utterance,
        frame.subject_constraints[:2] if membership else frame.subject_constraints,
        descriptors,
    )
    fragment_property = None
    if subject_fragment is not None:
        properties = next(
            (
                descriptor.get("properties")
                for descriptor in descriptors
                if descriptor.get("kind") == "object" and descriptor.get("name") == object_type
            ),
            None,
        )
        if not isinstance(properties, Mapping):
            return None
        fragment_properties = (
            ("parent_id",)
            if allowed_properties == frozenset({"parent_id"})
            else ("name", "label", "id")
        )
        fragment_property = next(
            (
                property_name
                for property_name in fragment_properties
                if isinstance(properties.get(property_name), Mapping)
                and not isinstance(properties[property_name].get("values"), list)
            ),
            None,
        )
        if fragment_property is None:
            return None
    if membership and fragment_property != "parent_id":
        # Without its exact group a membership frame would read every Resource in scope.
        return None
    # A name-filtered list frame may narrow by its verbatim fragment alone.
    fragment_only = fragment_property is not None and "name" in frame.measure_concepts
    if not filters and not fragment_only and allowed_properties != frozenset({"parent_id"}):
        return None
    predicates: list[dict[str, Any]] = []
    if fragment_property is not None:
        predicates.append({"property": fragment_property, "operator": "exists"})
    if fragment_property == "parent_id":
        predicates.extend(
            {
                "property": "type",
                "operator": "not_equals",
                "equals": resource_type,
            }
            for resource_type in OPERATIONAL_RESOURCE_EXCLUDED_TYPES
        )
        member_types = _member_type_values(frame.subject_constraints, subject_fragment, descriptors)
        if member_types is None:
            return None
        if len(member_types) == 1:
            predicates.append({"property": "type", "operator": "equals", "equals": member_types[0]})
        elif member_types:
            predicates.append({"property": "type", "operator": "in", "values": list(member_types)})
    predicates.extend(
        {"property": property_name, "operator": "exists"}
        for filter_type, property_name in sorted(filters)
        if filter_type == object_type
    )
    proposal = QueryPlanProposal(
        nodes=(
            QueryNodeProposal(
                node_id="stated-value-filter",
                kind=QueryNodeKind.OBJECT_SET,
                arguments={
                    "definition": {
                        "selector": {"kind": "object_type", "name": object_type},
                        "predicates": predicates,
                        "as_of": evaluation_time.astimezone(UTC).isoformat(),
                        "purpose": purpose,
                        "limit": 1000,
                        "include_relationships": False,
                    }
                },
                output_kind="query.table",
            ),
        ),
        output_node_ids=("stated-value-filter",),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    plan, grounded = ground_stated_value_filters(
        plan,
        utterance=utterance,
        descriptors=descriptors,
        subject_constraints=frame.subject_constraints[:2]
        if membership
        else frame.subject_constraints,
        allowed_properties=allowed_properties,
    )
    required_grounding = {
        f"{filter_type}.{property_name}" for filter_type, property_name in filters
    }
    if fragment_property is not None:
        required_grounding.add(f"{object_type}.{fragment_property}")
    if not required_grounding <= set(grounded):
        return None
    verifier.verify(plan, manifest=manifest)
    if fragment_property == "parent_id":
        return _resource_group_membership_plan(
            plan,
            verifier=verifier,
            frame=frame,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
        )
    return plan


def _member_type_values(
    subject_constraints: tuple[str, ...],
    group: str | None,
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...] | None:
    """Return the Resource types that typed member filters beside one group bind to.

    Only the judgment's own subtype phrases, carried after the group, narrow members;
    words that describe the container never do. A phrase that binds nothing voids
    the plan rather than widening the members.
    """

    object_names = {str(item.get("name")) for item in descriptors if item.get("kind") == "object"}
    values: list[str] = []
    for phrase in subject_constraints:
        if phrase == group or phrase in object_names:
            continue
        bound = stated_value_filters(phrase, descriptors, allowed_properties=frozenset({"type"}))
        types = bound.get(("Resource", "type"), ())
        if not types:
            return None
        # The container's own kind word describes the group; groups never contain groups.
        if set(types) == {_RESOURCE_GROUP_TYPE}:
            continue
        values.extend(item for item in types if item not in values)
    return tuple(values)


def _resource_group_membership_plan(
    grounded: OntologyQueryPlan,
    *,
    verifier: OntologyQueryPlanVerifier,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Read members through reviewed containment from the exact named group.

    A ``parent_id`` substring selects every resource whose parent identifier
    merely contains the stated name, including members of other groups whose
    names share it. Members are instead the reached endpoints of the one
    transitive containment LinkType from the single exact group object.
    """

    definition = grounded.nodes[0].arguments["definition"]
    predicates = [dict(item) for item in definition["predicates"]]
    group_names = [
        item["equals"]
        for item in predicates
        if item.get("property") == "parent_id" and item.get("operator") == "contains"
    ]
    selection = select_relation_sides(
        manifest.descriptors,
        anchor_type=_RESOURCE_OBJECT_TYPE,
        sense=RelationSense.CONTAINMENT,
        scope=RelationScope.ONE_SENSE,
        position=SubjectPosition.SOURCE,
        reach=RelationReach.TRANSITIVE,
    )
    sides = tuple(side for side in selection.sides if side.endpoint_type == _RESOURCE_OBJECT_TYPE)
    if len(group_names) != 1 or not isinstance(group_names[0], str) or len(sides) != 1:
        return None
    side = sides[0]
    endpoint_predicates = [item for item in predicates if item.get("property") != "parent_id"]
    as_of = evaluation_time.astimezone(UTC).isoformat()
    proposal = QueryPlanProposal(
        nodes=(
            QueryNodeProposal(
                node_id=_GROUP_ANCHOR_NODE_ID,
                kind=QueryNodeKind.OBJECT_SET,
                arguments={
                    "definition": {
                        "selector": {"kind": "object_type", "name": _RESOURCE_OBJECT_TYPE},
                        "predicates": [
                            {
                                "property": "name",
                                "operator": "equals_ignore_case",
                                "equals": group_names[0],
                            },
                            {
                                "property": "type",
                                "operator": "equals",
                                "equals": _RESOURCE_GROUP_TYPE,
                            },
                        ],
                        "as_of": as_of,
                        "purpose": purpose,
                        "limit": 2,
                        "include_relationships": False,
                    }
                },
                output_kind="query.table",
            ),
            QueryNodeProposal(
                node_id=_GROUP_MEMBERS_NODE_ID,
                kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                depends_on=(_GROUP_ANCHOR_NODE_ID,),
                arguments={
                    "selector": {"kind": "object_type", "name": side.endpoint_type},
                    "link_types": [side.link_type],
                    "direction": side.direction,
                    "max_depth": side.max_depth,
                    "as_of": as_of,
                    "purpose": purpose,
                    "limit": 1000,
                    **({"endpoint_predicates": endpoint_predicates} if endpoint_predicates else {}),
                },
                output_kind="query.table",
            ),
        ),
        output_node_ids=(_GROUP_MEMBERS_NODE_ID,),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    try:
        return verifier.verify(plan, manifest=manifest)
    except (PermissionError, ValueError):
        return None


__all__ = [
    "build_anchored_incident_plan",
    "build_inventory_document_plan",
    "build_stated_value_filter_plan",
]
