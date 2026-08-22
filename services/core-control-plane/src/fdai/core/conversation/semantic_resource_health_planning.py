"""Compile collection-scoped Resource Health reads from verified semantic frames."""

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
from fdai.core.ontology_platform.resource_health_queries import (
    RESOURCE_HEALTH_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_MEASURE_CONCEPTS,
)

from .semantic_planning_models import SemanticOutputShape
from .semantic_resource_state_planning import resource_collection_definition

_STATE_MEASURES = frozenset(RESOURCE_STATE_MEASURE_CONCEPTS)


def compile_resource_health_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build a secured collection followed by the exact Resource Health function."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_HEALTH_LIST
        or not _has_health_function(manifest.descriptors)
    ):
        return None
    health_concepts = tuple(
        sorted(item for item in frame.measure_concepts if item.startswith("resource_health."))
    )
    if not health_concepts:
        return None
    state_concepts = tuple(sorted(_STATE_MEASURES.intersection(frame.measure_concepts)))
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    nodes = (
        OntologyQueryNode(
            node_id="resource-health-scope",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-health-filter",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("resource-health-scope",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_HEALTH_FUNCTION_NAME,
                    "arguments": {
                        "health_concepts": list(health_concepts),
                        "state_concepts": list(state_concepts),
                    },
                    "dependency_arguments": {"resource-health-scope": "query_result"},
                }
            ),
            output_kind="query.table",
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
        "output_node_ids": ["resource-health-filter"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-health-filter",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _has_health_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_HEALTH_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_resource_health_plan"]
