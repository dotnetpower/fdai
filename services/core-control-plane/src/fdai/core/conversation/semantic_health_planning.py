"""Compile exact-target health evidence assessments from verified request facts."""

from __future__ import annotations

import logging
import re
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
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_health_assessment_queries import (
    TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
)

from .semantic_planning_models import (
    SemanticOutputShape,
)

_LOGGER = logging.getLogger(__name__)
_RUNTIME_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}"
    r"(?![A-Za-z0-9_.-])"
)
_HEALTH_WINDOW = timedelta(minutes=30)
_METRIC_CONCEPTS = (
    ("health-cpu", "resource.saturation", "resource_saturation"),
    ("health-request-volume", "request.volume", "request_volume"),
    ("health-request-errors", "request.errors", "request_errors"),
)


def compile_target_health_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build a bounded exact-target health evidence assessment with no action authority."""

    if (
        frame.output_shape != SemanticOutputShape.TARGET_HEALTH_ASSESSMENT
        or not _has_required_functions(manifest.descriptors)
    ):
        return None
    target_name = _exact_target(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )
    identity_property = _resource_identity_property(manifest.descriptors)
    if target_name is None or identity_property is None:
        return None
    end = evaluation_time.astimezone(UTC)
    start = end - _HEALTH_WINDOW
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=target_name,
            ),
        ),
        as_of=end,
        purpose=purpose,
        limit=2,
    )
    nodes: tuple[OntologyQueryNode, ...] = (
        _node(
            "health-target",
            QueryNodeKind.OBJECT_SET,
            arguments={"definition": target_definition.model_dump(mode="json")},
            output_kind="query.table",
        ),
        _function_node(
            "health-current-state",
            function_name=RESOURCE_CURRENT_STATE_FUNCTION_NAME,
            depends_on=("health-target",),
            dependency_arguments={"health-target": "query_result"},
        ),
        _function_node(
            "health-activity",
            function_name=RESOURCE_ACTIVITY_FUNCTION_NAME,
            depends_on=("health-target",),
            arguments={"lookback_seconds": int(_HEALTH_WINDOW.total_seconds())},
            dependency_arguments={"health-target": "query_result"},
        ),
        *(
            _node(
                node_id,
                QueryNodeKind.METRIC_SCOPE_SERIES,
                depends_on=("health-target",),
                arguments={
                    "concept_id": concept_id,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
                output_kind="metric.window",
            )
            for node_id, concept_id, _argument_name in _METRIC_CONCEPTS
        ),
        _function_node(
            "target-health-assessment",
            function_name=TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
            depends_on=(
                "health-current-state",
                "health-activity",
                *tuple(node_id for node_id, _concept_id, _argument_name in _METRIC_CONCEPTS),
            ),
            dependency_arguments={
                "health-current-state": "current_state",
                "health-activity": "activity",
                **{
                    node_id: argument_name
                    for node_id, _concept_id, argument_name in _METRIC_CONCEPTS
                },
            },
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
        "output_node_ids": ["target-health-assessment"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("target-health-assessment",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _exact_target(
    subject_constraints: tuple[str, ...],
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    runtime_targets = tuple(match.group(0) for match in _RUNTIME_TARGET.finditer(utterance))
    has_resource = any(
        item.get("kind") == "object" and item.get("name") == "Resource" for item in descriptors
    )
    if len(runtime_targets) == 1 and has_resource:
        return runtime_targets[0]
    if runtime_targets:
        return None
    declared = {
        name.casefold()
        for item in descriptors
        if item.get("kind") in {"object", "interface"}
        if isinstance((name := item.get("name")), str)
    }
    folded = utterance.casefold()
    candidates = tuple(
        subject
        for subject in subject_constraints
        if subject.casefold() not in declared
        if folded.count(subject.casefold()) == 1
    )
    return candidates[0] if len(candidates) == 1 else None


def _resource_identity_property(descriptors: tuple[dict[str, Any], ...]) -> str | None:
    selected = tuple(
        item
        for item in descriptors
        if item.get("kind") == "object" and item.get("name") == "Resource"
    )
    if len(selected) != 1 or not isinstance(selected[0].get("properties"), Mapping):
        return None
    properties = selected[0]["properties"]
    return next((name for name in ("name", "display_name", "id") if name in properties), None)


def _has_required_functions(descriptors: tuple[dict[str, Any], ...]) -> bool:
    names = {
        name
        for item in descriptors
        if item.get("kind") == "function"
        if isinstance((name := item.get("name")), str)
    }
    return {
        RESOURCE_ACTIVITY_FUNCTION_NAME,
        RESOURCE_CURRENT_STATE_FUNCTION_NAME,
        TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
    } <= names


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


def _function_node(
    node_id: str,
    *,
    function_name: str,
    depends_on: tuple[str, ...],
    arguments: dict[str, object] | None = None,
    dependency_arguments: dict[str, str],
) -> OntologyQueryNode:
    return _node(
        node_id,
        QueryNodeKind.FUNCTION,
        depends_on=depends_on,
        arguments={
            "function_name": function_name,
            "arguments": arguments or {},
            "dependency_arguments": dependency_arguments,
        },
        output_kind="query.table",
    )


__all__ = ["compile_target_health_plan"]
