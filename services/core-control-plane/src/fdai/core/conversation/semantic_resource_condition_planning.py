"""Compile multi-source Resource condition reads without merging source authority."""

from __future__ import annotations

from datetime import datetime
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
from fdai.core.ontology_platform.resource_health_queries import RESOURCE_HEALTH_FUNCTION_NAME
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_QUERY_CONCEPTS,
)

from .semantic_planning_models import SemanticOutputShape
from .semantic_resource_state_planning import resource_collection_definition


def compile_resource_condition_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build independent inventory-state and Resource Health output sections."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_CONDITION_SECTIONS
        or not _has_function(manifest.descriptors, RESOURCE_STATE_FUNCTION_NAME)
        or not _has_function(manifest.descriptors, RESOURCE_HEALTH_FUNCTION_NAME)
    ):
        return None
    state_concepts = tuple(
        sorted(set(frame.measure_concepts).intersection(RESOURCE_STATE_QUERY_CONCEPTS))
    )
    health_concepts = tuple(
        sorted(item for item in frame.measure_concepts if item.startswith("resource_health."))
    )
    if not state_concepts or not health_concepts:
        return None
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    scope_id = "resource-condition-scope"
    nodes = (
        OntologyQueryNode(
            node_id=scope_id,
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-condition-power",
            kind=QueryNodeKind.FUNCTION,
            depends_on=(scope_id,),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_STATE_FUNCTION_NAME,
                    "arguments": {"state_concepts": list(state_concepts)},
                    "dependency_arguments": {scope_id: "query_result"},
                }
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-condition-health",
            kind=QueryNodeKind.FUNCTION,
            depends_on=(scope_id,),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_HEALTH_FUNCTION_NAME,
                    "arguments": {
                        "health_concepts": list(health_concepts),
                        "state_concepts": [],
                    },
                    "dependency_arguments": {scope_id: "query_result"},
                }
            ),
            output_kind="query.table",
        ),
    )
    output_node_ids = ("resource-condition-power", "resource-condition-health")
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


def _has_function(descriptors: tuple[dict[str, Any], ...], function_name: str) -> bool:
    return any(
        descriptor.get("kind") == "function" and descriptor.get("name") == function_name
        for descriptor in descriptors
    )


__all__ = ["compile_resource_condition_plan"]
