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
from .session import Principal

_INCIDENT_EVIDENCE_NODE_ID = "bound_incident_evidence"


_RESOURCE_GROUP_MEMBER_EXCLUDED_TYPES = ("authorization.role-assignment",)


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
    subject_fragment = stated_subject_fragment(
        utterance,
        frame.subject_constraints,
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
    if not filters and allowed_properties != frozenset({"parent_id"}):
        return None
    predicates = []
    if fragment_property is not None:
        predicates.append({"property": fragment_property, "operator": "exists"})
    if fragment_property == "parent_id":
        predicates.extend(
            {
                "property": "type",
                "operator": "not_equals",
                "equals": resource_type,
            }
            for resource_type in _RESOURCE_GROUP_MEMBER_EXCLUDED_TYPES
        )
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
        subject_constraints=frame.subject_constraints,
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
    return plan


__all__ = [
    "build_anchored_incident_plan",
    "build_stated_value_filter_plan",
]
