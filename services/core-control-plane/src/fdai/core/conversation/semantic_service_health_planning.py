"""Compile active Service Health reads from a verified semantic frame."""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_ALL_MEASURE_CONCEPTS,
    SERVICE_HEALTH_EVENT_TYPE_MEASURES,
    SERVICE_HEALTH_FUNCTION_NAME,
    SERVICE_HEALTH_MEASURE_CONCEPTS,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    query_signal_matches,
)

from .semantic_planning_frame import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape

_EVENT_TYPE_SIGNAL = {
    "service_issue": "service_health_issue",
    "planned_maintenance": "service_health_maintenance",
    "health_advisory": "service_health_advisory",
}


def normalize_service_health_event_types(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    context: tuple[str, ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Bind a Service Health frame to reviewed event types stated by the operator."""

    if (
        proposal.operation is not SemanticOperation.SELECT
        or proposal.output_shape != SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH
    ):
        return None
    selected = tuple(
        SERVICE_HEALTH_EVENT_TYPE_MEASURES[event_type]
        for event_type, signal in _EVENT_TYPE_SIGNAL.items()
        if query_signal_matches(utterance, inventory_query_language, signal)
    )
    measures = selected or SERVICE_HEALTH_MEASURE_CONCEPTS
    normalized = proposal.model_copy(update={"measure_concepts": measures})
    return normalized, build_semantic_frame(normalized, utterance=utterance, context=context)


def compile_service_health_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build the exact no-input active Service Health Function node."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH
        or not frame.measure_concepts
        or not set(frame.measure_concepts) <= set(SERVICE_HEALTH_ALL_MEASURE_CONCEPTS)
        or not _has_service_health_function(manifest.descriptors)
    ):
        return None
    selected_event_types = tuple(
        event_type
        for event_type, measure in SERVICE_HEALTH_EVENT_TYPE_MEASURES.items()
        if measure in frame.measure_concepts
    )
    node = OntologyQueryNode(
        node_id="subscription-service-health",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": SERVICE_HEALTH_FUNCTION_NAME,
                "arguments": (
                    {"event_types": list(selected_event_types)} if selected_event_types else {}
                ),
                "dependency_arguments": {},
            }
        ),
        output_kind="query.table",
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": [node.node_id],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=(node,),
        output_node_ids=(node.node_id,),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _has_service_health_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == SERVICE_HEALTH_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_service_health_plan", "normalize_service_health_event_types"]
