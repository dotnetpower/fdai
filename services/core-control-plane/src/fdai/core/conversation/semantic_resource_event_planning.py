"""Compile bounded Resource event history from verified semantic frames."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

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
from fdai.core.ontology_platform.resource_event_queries import (
    RESOURCE_EVENT_FUNCTION_NAME,
    RESOURCE_EVENT_MEASURE_CONCEPTS,
)

from .semantic_planning_models import SemanticOutputShape
from .semantic_resource_state_planning import resource_collection_definition

_EVENT_MEASURES = frozenset(RESOURCE_EVENT_MEASURE_CONCEPTS)


def compile_resource_event_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build a secured collection followed by the exact event-history function."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_EVENT_HISTORY
        or not _has_event_function(manifest.descriptors)
    ):
        return None
    event_families = tuple(sorted(_EVENT_MEASURES.intersection(frame.measure_concepts)))
    if not event_families or len(event_families) != len(frame.measure_concepts):
        return None
    lookback_seconds = _lookback_seconds(frame.temporal_scope)
    if lookback_seconds is None:
        return None
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    nodes = (
        OntologyQueryNode(
            node_id="resource-event-scope",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-event-history",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("resource-event-scope",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_EVENT_FUNCTION_NAME,
                    "arguments": {
                        "event_families": list(event_families),
                        "lookback_seconds": lookback_seconds,
                    },
                    "dependency_arguments": {"resource-event-scope": "query_result"},
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
        "output_node_ids": ["resource-event-history"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-event-history",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _lookback_seconds(temporal_scope: dict[str, Any]) -> int | None:
    if set(temporal_scope) != {"lookback_seconds"}:
        return None
    value = temporal_scope["lookback_seconds"]
    if isinstance(value, bool) or not isinstance(value, int) or not 60 <= value <= 86_400:
        return None
    return cast(int, value)


def _has_event_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_EVENT_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_resource_event_plan"]
