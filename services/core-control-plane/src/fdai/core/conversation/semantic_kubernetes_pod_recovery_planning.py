"""Compile exact-target Kubernetes Pod restart and recovery reads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
    KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
    KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
)

from .semantic_investigation import InvestigationEntityRole, VerifiedInvestigationIntent

_RESTART_HISTORY_WINDOW = timedelta(minutes=30)


def compile_kubernetes_pod_recovery_plan(
    *,
    frame: SemanticProblemFrame,
    investigation_intent: VerifiedInvestigationIntent | None,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    available_metric_concepts: tuple[str, ...],
) -> OntologyQueryPlan | None:
    """Build an exact Pod read for a verified restart symptom."""

    if (
        investigation_intent is None
        or not _has_function(manifest.descriptors)
        or KUBERNETES_POD_RESTART_HISTORY_CONCEPT not in available_metric_concepts
    ):
        return None
    primary_measure = next(
        (
            measure
            for measure in investigation_intent.symptom_measures
            if measure.measure_id == investigation_intent.primary_symptom_measure_id
        ),
        None,
    )
    if (
        primary_measure is None
        or primary_measure.concept_id != KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT
    ):
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
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=targets[0].span.text,
            ),
        ),
        as_of=evaluation_time.astimezone(UTC),
        purpose=purpose,
        limit=2,
    )
    nodes = (
        OntologyQueryNode(
            node_id="pod-recovery-target",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json(
                {"definition": target_definition.model_dump(mode="json")}
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="pod-restart-history",
            kind=QueryNodeKind.METRIC_SCOPE_SERIES,
            depends_on=("pod-recovery-target",),
            arguments_json=canonical_json(
                {
                    "concept_id": KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
                    "start": (evaluation_time - _RESTART_HISTORY_WINDOW).isoformat(),
                    "end": evaluation_time.isoformat(),
                }
            ),
            output_kind="metric.window",
        ),
        OntologyQueryNode(
            node_id="pod-recovery-controller",
            kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            depends_on=("pod-recovery-target",),
            arguments_json=canonical_json(
                {
                    "selector": {
                        "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                        "name": "Resource",
                    },
                    "link_types": ["kubernetes_owned_by"],
                    "direction": "outgoing",
                    "max_depth": 1,
                    "as_of": evaluation_time.isoformat(),
                    "purpose": purpose,
                    "limit": 2,
                }
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="pod-recovery-deployment",
            kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            depends_on=("pod-recovery-controller",),
            arguments_json=canonical_json(
                {
                    "selector": {
                        "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                        "name": "Resource",
                    },
                    "link_types": ["kubernetes_owned_by"],
                    "direction": "outgoing",
                    "max_depth": 1,
                    "as_of": evaluation_time.isoformat(),
                    "purpose": purpose,
                    "limit": 2,
                }
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="pod-recovery-evidence",
            kind=QueryNodeKind.FUNCTION,
            depends_on=(
                "pod-recovery-target",
                "pod-restart-history",
                "pod-recovery-controller",
                "pod-recovery-deployment",
            ),
            arguments_json=canonical_json(
                {
                    "function_name": KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
                    "arguments": {},
                    "dependency_arguments": {
                        "pod-recovery-target": "pod_query_result",
                        "pod-restart-history": "restart_history",
                        "pod-recovery-controller": "controller_query_result",
                        "pod-recovery-deployment": "deployment_query_result",
                    },
                }
            ),
            output_kind="kubernetes.pod.recovery.evidence",
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
        "output_node_ids": ["pod-recovery-evidence"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("pod-recovery-evidence",),
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


def _has_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == KUBERNETES_POD_RECOVERY_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_kubernetes_pod_recovery_plan"]
