"""Compile exact-target Kubernetes rollout evidence reads."""

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
from fdai.core.ontology_platform.kubernetes_rollout_queries import (
    KUBERNETES_ROLLOUT_FUNCTION_NAME,
    KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
)

from .semantic_investigation import InvestigationEntityRole, VerifiedInvestigationIntent


def compile_kubernetes_rollout_plan(
    *,
    frame: SemanticProblemFrame,
    investigation_intent: VerifiedInvestigationIntent | None,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build an exact Deployment ownership read for a verified rollout symptom."""

    if investigation_intent is None or not _has_rollout_function(manifest.descriptors):
        return None
    primary_measure = next(
        (
            measure
            for measure in investigation_intent.symptom_measures
            if measure.measure_id == investigation_intent.primary_symptom_measure_id
        ),
        None,
    )
    if primary_measure is None or primary_measure.concept_id != KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT:
        return None
    targets = tuple(
        entity
        for entity in investigation_intent.entities
        if entity.role is InvestigationEntityRole.AFFECTED_TARGET
    )
    if len(targets) != 1 or targets[0].object_type_candidates != ("Resource",):
        return None
    identity_property = _resource_identity_property(manifest.descriptors)
    if identity_property is None:
        return None
    target_value = targets[0].span.text
    as_of = evaluation_time.astimezone(UTC)
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=target_value,
            ),
        ),
        as_of=as_of,
        purpose=purpose,
        limit=2,
    )
    nodes = (
        _node(
            "rollout-target",
            QueryNodeKind.OBJECT_SET,
            arguments={"definition": target_definition.model_dump(mode="json")},
            output_kind="query.table",
        ),
        _node(
            "rollout-controllers",
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            depends_on=("rollout-target",),
            arguments={
                "selector": {
                    "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                    "name": "Resource",
                },
                "link_types": ["kubernetes_owned_by"],
                "direction": "incoming",
                "max_depth": 1,
                "as_of": as_of.isoformat(),
                "purpose": purpose,
                "limit": 128,
            },
            output_kind="query.table",
        ),
        _node(
            "rollout-pods",
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            depends_on=("rollout-controllers",),
            arguments={
                "selector": {
                    "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                    "name": "Resource",
                },
                "link_types": ["kubernetes_owned_by"],
                "direction": "incoming",
                "max_depth": 1,
                "as_of": as_of.isoformat(),
                "purpose": purpose,
                "limit": 128,
            },
            output_kind="query.table",
        ),
        _node(
            "rollout-evidence",
            QueryNodeKind.FUNCTION,
            depends_on=("rollout-target", "rollout-controllers", "rollout-pods"),
            arguments={
                "function_name": KUBERNETES_ROLLOUT_FUNCTION_NAME,
                "arguments": {},
                "dependency_arguments": {
                    "rollout-target": "deployment_query_result",
                    "rollout-controllers": "controller_query_result",
                    "rollout-pods": "pod_query_result",
                },
            },
            output_kind="kubernetes.rollout.evidence",
        ),
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": ["rollout-evidence"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("rollout-evidence",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _resource_identity_property(descriptors: tuple[dict[str, Any], ...]) -> str | None:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
    )
    if len(selected) != 1 or not isinstance(selected[0].get("properties"), Mapping):
        return None
    properties = selected[0]["properties"]
    return next((name for name in ("name", "display_name", "id") if name in properties), None)


def _has_rollout_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == KUBERNETES_ROLLOUT_FUNCTION_NAME
        for descriptor in descriptors
    )


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


__all__ = ["compile_kubernetes_rollout_plan"]
