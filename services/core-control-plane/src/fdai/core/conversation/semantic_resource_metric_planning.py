"""Compile bounded Resource metric reads from verified semantic frames."""

from __future__ import annotations

from collections.abc import Mapping
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

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.resource_metric_queries import (
    MAX_RESOURCE_METRIC_WINDOW_SECONDS,
    RESOURCE_METRIC_FUNCTION_NAME,
    RESOURCE_METRIC_SERIES_FUNCTION_NAME,
)

from .semantic_current_state_planning import exact_target_from_constraints
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_resource_state_planning import resource_collection_definition

_DEFAULT_WINDOW_SECONDS = 900
_NORMALIZABLE_SERIES_OUTPUTS = frozenset(
    {
        SemanticOutputShape.EVIDENCE_VALIDATION,
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
        SemanticOutputShape.RESOURCE_METRIC_LIST,
        SemanticOutputShape.TARGET_RESOURCE_METRIC,
        SemanticOutputShape.TEMPORAL_COMPARISON,
    }
)
_READ_ONLY_SERIES_OPERATIONS = frozenset(
    {
        SemanticOperation.COMPARE,
        SemanticOperation.SELECT,
        SemanticOperation.VALIDATE,
    }
)
_SERIES_REQUEST_TERMS = (
    "chart",
    "graph",
    "plot",
    "time series",
    "timeseries",
    "trend",
    "visualization",
    "visualize",
    "그래프",
    "시각화",
    "차트",
    "추이",
)


def normalize_exact_resource_metric_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> SemanticFrameProposal:
    """Bind exact metric aggregate and visualization requests to fixed output families."""

    if (
        proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape is SemanticOutputShape.TARGET_RESOURCE_METRIC_SERIES
    ):
        return proposal
    if (
        proposal.operation not in _READ_ONLY_SERIES_OPERATIONS
        or proposal.output_shape not in _NORMALIZABLE_SERIES_OUTPUTS
        or proposal.investigation is not None
        or proposal.unresolved_terms
        or proposal.clarification_requirements
        or exact_target_from_constraints(
            proposal.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is None
    ):
        return proposal
    output_shape = SemanticOutputShape.TARGET_RESOURCE_METRIC
    if len(proposal.measure_concepts) == 1 and _requests_metric_series(utterance):
        return proposal.model_copy(
            update={
                "operation": SemanticOperation.SELECT,
                "output_shape": SemanticOutputShape.TARGET_RESOURCE_METRIC_SERIES,
            }
        )
    if proposal.output_shape is SemanticOutputShape.RESOURCE_METRIC_LIST:
        return proposal.model_copy(update={"output_shape": output_shape})
    return proposal


def _requests_metric_series(utterance: str) -> bool:
    normalized = utterance.casefold()
    return any(term in normalized for term in _SERIES_REQUEST_TERMS)


def compile_resource_metric_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    available_metric_concepts: tuple[str, ...],
) -> OntologyQueryPlan | None:
    """Build a secured collection followed by reviewed metric reads."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_METRIC_LIST
        or not _has_metric_function(manifest.descriptors)
    ):
        return None
    available = frozenset(available_metric_concepts)
    metric_concepts = tuple(sorted(set(frame.measure_concepts).intersection(available)))
    if not metric_concepts or len(metric_concepts) != len(frame.measure_concepts):
        return None
    window_seconds = _window_seconds(frame.temporal_scope)
    if window_seconds is None:
        return None
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    nodes = (
        OntologyQueryNode(
            node_id="resource-metric-scope",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-metric-read",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("resource-metric-scope",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_METRIC_FUNCTION_NAME,
                    "arguments": {
                        "metric_concepts": list(metric_concepts),
                        "window_seconds": window_seconds,
                    },
                    "dependency_arguments": {"resource-metric-scope": "query_result"},
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
        "output_node_ids": ["resource-metric-read"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-metric-read",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def compile_exact_resource_metric_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    available_metric_concepts: tuple[str, ...],
) -> OntologyQueryPlan | None:
    """Build one exact Resource metric read with a bounded reviewed window."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.TARGET_RESOURCE_METRIC
        or not _has_metric_function(manifest.descriptors)
    ):
        return None
    available = frozenset(available_metric_concepts)
    metric_concepts = tuple(sorted(set(frame.measure_concepts).intersection(available)))
    window_seconds = _window_seconds(frame.temporal_scope)
    target_name = exact_target_from_constraints(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )
    identity_property = _resource_identity_property(manifest.descriptors)
    if (
        not metric_concepts
        or len(metric_concepts) != len(frame.measure_concepts)
        or window_seconds is None
        or target_name is None
        or identity_property is None
    ):
        return None
    collection = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    definition = collection.model_copy(
        update={
            "predicates": (
                *collection.predicates,
                ObjectPredicate(
                    property=identity_property,
                    operator=ObjectPredicateOperator.EQUALS,
                    equals=target_name,
                ),
            ),
            "limit": 2,
        }
    )
    nodes = (
        OntologyQueryNode(
            node_id="target-metric-scope",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="target-metric-read",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("target-metric-scope",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_METRIC_FUNCTION_NAME,
                    "arguments": {
                        "metric_concepts": list(metric_concepts),
                        "window_seconds": window_seconds,
                    },
                    "dependency_arguments": {"target-metric-scope": "query_result"},
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
        "output_node_ids": ["target-metric-read"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("target-metric-read",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def compile_exact_resource_metric_series_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    available_metric_concepts: tuple[str, ...],
) -> OntologyQueryPlan | None:
    """Build one exact Resource metric series with a bounded reviewed window."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.TARGET_RESOURCE_METRIC_SERIES
        or not _has_metric_series_function(manifest.descriptors)
    ):
        return None
    available = frozenset(available_metric_concepts)
    metric_concepts = tuple(sorted(set(frame.measure_concepts).intersection(available)))
    window_seconds = _window_seconds(frame.temporal_scope)
    target_name = exact_target_from_constraints(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )
    identity_property = _resource_identity_property(manifest.descriptors)
    if (
        len(metric_concepts) != 1
        or len(metric_concepts) != len(frame.measure_concepts)
        or window_seconds is None
        or target_name is None
        or identity_property is None
    ):
        return None
    collection = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
    )
    definition = collection.model_copy(
        update={
            "predicates": (
                *collection.predicates,
                ObjectPredicate(
                    property=identity_property,
                    operator=ObjectPredicateOperator.EQUALS,
                    equals=target_name,
                ),
            ),
            "limit": 2,
        }
    )
    scope_node_id = "target-metric-series-scope"
    output_node_id = "target-metric-series"
    nodes = (
        OntologyQueryNode(
            node_id=scope_node_id,
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id=output_node_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=(scope_node_id,),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_METRIC_SERIES_FUNCTION_NAME,
                    "arguments": {
                        "metric_concept": metric_concepts[0],
                        "window_seconds": window_seconds,
                    },
                    "dependency_arguments": {scope_node_id: "query_result"},
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
        "output_node_ids": [output_node_id],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=(output_node_id,),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _window_seconds(temporal_scope: dict[str, Any]) -> int | None:
    if not temporal_scope:
        return _DEFAULT_WINDOW_SECONDS
    if set(temporal_scope) != {"lookback_seconds"}:
        return None
    value = temporal_scope["lookback_seconds"]
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 300 <= value <= MAX_RESOURCE_METRIC_WINDOW_SECONDS
    ):
        return None
    return int(value)


def _has_metric_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_METRIC_FUNCTION_NAME
        for descriptor in descriptors
    )


def _has_metric_series_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_METRIC_SERIES_FUNCTION_NAME
        for descriptor in descriptors
    )


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


__all__ = [
    "compile_exact_resource_metric_plan",
    "compile_exact_resource_metric_series_plan",
    "compile_resource_metric_plan",
    "normalize_exact_resource_metric_proposal",
]
