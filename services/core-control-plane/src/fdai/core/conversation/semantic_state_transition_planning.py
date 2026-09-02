"""Compile bounded Resource operational-state transition history."""

from __future__ import annotations

from datetime import datetime, timedelta
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
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_MEASURE_CONCEPTS,
    RESOURCE_STATE_OBSERVED_CONCEPT,
    RESOURCE_STATE_QUERY_CONCEPTS,
)
from fdai.core.ontology_platform.state_transitions import (
    RESOURCE_STATE_TRANSITION_TYPE,
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
)

from .semantic_planning_models import SemanticOutputShape
from .semantic_resource_state_planning import resource_collection_definition


def compile_resource_state_transition_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_STATE_TRANSITIONS
        or not _has_function(manifest.descriptors)
    ):
        return None
    lookback_seconds = frame.temporal_scope.get("lookback_seconds")
    state_concepts = tuple(
        sorted(set(frame.measure_concepts).intersection(RESOURCE_STATE_QUERY_CONCEPTS))
    )
    if (
        not isinstance(lookback_seconds, int)
        or isinstance(lookback_seconds, bool)
        or not 60 <= lookback_seconds <= 86_400
        or not state_concepts
    ):
        return None
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    scope_id = "resource-transition-scope"
    transition_id = "resource-state-transitions"
    start_at = evaluation_time - timedelta(seconds=lookback_seconds)
    to_states = (
        tuple(
            concept.removeprefix("resource_state.") for concept in RESOURCE_STATE_MEASURE_CONCEPTS
        )
        if state_concepts == (RESOURCE_STATE_OBSERVED_CONCEPT,)
        else tuple(concept.removeprefix("resource_state.") for concept in state_concepts)
    )
    nodes = (
        OntologyQueryNode(
            node_id=scope_id,
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id=transition_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=(scope_id,),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
                    "arguments": {
                        "state_types": [RESOURCE_STATE_TRANSITION_TYPE],
                        "to_states": list(to_states),
                        "start_at": start_at.isoformat(),
                        "end_at": evaluation_time.isoformat(),
                        "known_at": evaluation_time.isoformat(),
                        "limit": 256,
                    },
                    "dependency_arguments": {scope_id: "query_result"},
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
        "output_node_ids": [transition_id],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=(transition_id,),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _has_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_resource_state_transition_plan"]
