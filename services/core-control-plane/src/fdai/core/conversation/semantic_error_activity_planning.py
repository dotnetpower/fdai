"""Compile exact-target request-error and Activity Log correlation reads."""

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
from fdai.core.ontology_platform.resource_error_activity_correlation_queries import (
    ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
)

from .semantic_planning_models import SemanticOutputShape

_LOGGER = logging.getLogger(__name__)
_LOOKBACK = re.compile(
    r"(?:\b(?:last|past)\s+|지난\s*)(?P<count>\d{1,4})\s*"
    r"(?P<unit>minutes?|mins?|hours?|분|시간)\b"
)
_RUNTIME_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}"
    r"(?![A-Za-z0-9_.-])"
)


def compile_target_error_activity_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build aligned request-error windows and exact-target activity correlation."""

    if (
        frame.output_shape != SemanticOutputShape.TARGET_ERROR_ACTIVITY_CORRELATION
        or not _has_required_functions(manifest.descriptors)
    ):
        return None
    lookback = _lookback(utterance)
    target_name = _exact_target(utterance, descriptors=manifest.descriptors)
    identity_property = _resource_identity_property(manifest.descriptors)
    if lookback is None or target_name is None or identity_property is None:
        return None
    end = evaluation_time.astimezone(UTC)
    current_start = end - lookback
    baseline_start = current_start - lookback
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
    nodes = (
        _node(
            "error-activity-target",
            QueryNodeKind.OBJECT_SET,
            arguments={"definition": target_definition.model_dump(mode="json")},
            output_kind="query.table",
        ),
        _node(
            "baseline-request-errors",
            QueryNodeKind.METRIC_SCOPE_SERIES,
            depends_on=("error-activity-target",),
            arguments={
                "concept_id": "request.errors",
                "start": baseline_start.isoformat(),
                "end": current_start.isoformat(),
            },
            output_kind="metric.window",
        ),
        _node(
            "current-request-errors",
            QueryNodeKind.METRIC_SCOPE_SERIES,
            depends_on=("error-activity-target",),
            arguments={
                "concept_id": "request.errors",
                "start": current_start.isoformat(),
                "end": end.isoformat(),
            },
            output_kind="metric.window",
        ),
        _function_node(
            "current-resource-activity",
            function_name=RESOURCE_ACTIVITY_FUNCTION_NAME,
            depends_on=("error-activity-target",),
            arguments={"lookback_seconds": int(lookback.total_seconds())},
            dependency_arguments={"error-activity-target": "query_result"},
        ),
        _function_node(
            "target-error-activity-correlation",
            function_name=ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
            depends_on=(
                "baseline-request-errors",
                "current-request-errors",
                "current-resource-activity",
            ),
            dependency_arguments={
                "baseline-request-errors": "baseline_errors",
                "current-request-errors": "current_errors",
                "current-resource-activity": "activity",
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
        "output_node_ids": ["target-error-activity-correlation"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("target-error-activity-correlation",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _lookback(utterance: str) -> timedelta | None:
    matches = tuple(_LOOKBACK.finditer(utterance.casefold()))
    if len(matches) != 1:
        return None
    count = int(matches[0].group("count"))
    unit = matches[0].group("unit")
    seconds = count * (3600 if unit in {"hour", "hours", "시간"} else 60)
    return timedelta(seconds=seconds) if 60 <= seconds <= 86_400 else None


def _exact_target(
    utterance: str,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    targets = tuple(match.group(0) for match in _RUNTIME_TARGET.finditer(utterance))
    has_resource = any(
        item.get("kind") == "object" and item.get("name") == "Resource" for item in descriptors
    )
    return targets[0] if len(targets) == 1 and has_resource else None


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
        ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
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


__all__ = [
    "compile_target_error_activity_plan",
]
