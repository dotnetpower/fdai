"""Build the reviewed single-target health assessment read.

The current path and the question-form compiler read one Resource's health the same way:
its current state, its control-plane activity in a fixed window, three reviewed metric
windows, and the no-authority assessment that reduces them. This module holds that one
reviewed shape so both paths, and the independent verifier, agree on every argument.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
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

TARGET_HEALTH_WINDOW = timedelta(minutes=30)
# Each reviewed metric window: its node suffix, metric concept, and assessment argument.
TARGET_HEALTH_METRICS: tuple[tuple[str, str, str], ...] = (
    ("health-cpu", "resource.saturation", "resource_saturation"),
    ("health-request-volume", "request.volume", "request_volume"),
    ("health-request-errors", "request.errors", "request_errors"),
)
TARGET_HEALTH_FUNCTIONS = frozenset(
    {
        RESOURCE_CURRENT_STATE_FUNCTION_NAME,
        RESOURCE_ACTIVITY_FUNCTION_NAME,
        TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
    }
)
ASSESSMENT_NODE_SUFFIX = "target-health-assessment"


def target_health_window(evaluation_time: datetime) -> tuple[str, str]:
    """Return the fixed metric window that ends at the evaluation time, as ISO strings."""

    end = evaluation_time.astimezone(UTC)
    return (end - TARGET_HEALTH_WINDOW).isoformat(), end.isoformat()


def target_health_nodes(
    prefix: str, anchor_id: str, evaluation_time: datetime
) -> tuple[OntologyQueryNode, ...]:
    """Return the reviewed reads after one anchor, ending in the assessment node."""

    start, end = target_health_window(evaluation_time)
    state = _function(
        f"{prefix}-health-current-state",
        RESOURCE_CURRENT_STATE_FUNCTION_NAME,
        {},
        {anchor_id: "query_result"},
    )
    activity = _function(
        f"{prefix}-health-activity",
        RESOURCE_ACTIVITY_FUNCTION_NAME,
        {"lookback_seconds": int(TARGET_HEALTH_WINDOW.total_seconds())},
        {anchor_id: "query_result"},
    )
    metrics = tuple(
        OntologyQueryNode(
            node_id=f"{prefix}-{suffix}",
            kind=QueryNodeKind.METRIC_SCOPE_SERIES,
            depends_on=(anchor_id,),
            arguments_json=canonical_json({"concept_id": concept, "start": start, "end": end}),
            output_kind="metric.window",
        )
        for suffix, concept, _argument in TARGET_HEALTH_METRICS
    )
    dependencies = {
        state.node_id: "current_state",
        activity.node_id: "activity",
        **{f"{prefix}-{suffix}": argument for suffix, _concept, argument in TARGET_HEALTH_METRICS},
    }
    assessment = _function(
        f"{prefix}-{ASSESSMENT_NODE_SUFFIX}",
        TARGET_HEALTH_ASSESSMENT_FUNCTION_NAME,
        {},
        dependencies,
    )
    return (state, activity, *metrics, assessment)


def _function(
    node_id: str,
    name: str,
    arguments: dict[str, object],
    dependencies: dict[str, str],
) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id=node_id,
        kind=QueryNodeKind.FUNCTION,
        depends_on=tuple(dependencies),
        arguments_json=canonical_json(
            {
                "function_name": name,
                "arguments": arguments,
                "dependency_arguments": dependencies,
            }
        ),
        output_kind="query.table",
    )


__all__ = [
    "ASSESSMENT_NODE_SUFFIX",
    "TARGET_HEALTH_FUNCTIONS",
    "TARGET_HEALTH_METRICS",
    "TARGET_HEALTH_WINDOW",
    "target_health_nodes",
    "target_health_window",
]
