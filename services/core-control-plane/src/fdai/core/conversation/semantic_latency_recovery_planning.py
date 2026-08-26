"""Compile exact-service later-cutoff latency recovery evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
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
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.latency_recovery_evidence import (
    LATENCY_RECOVERY_FUNCTION_NAME,
)

from .semantic_impact_planning import service_resource_query_sides
from .semantic_planning_models import BoundInvestigationContinuation

_REQUIRED_MEASURES = ("dependency.latency", "service.latency")


class LatencyRecoveryWindowPendingError(ValueError):
    """The required non-overlapping recovery window has not elapsed."""


def compile_latency_recovery_plan(
    *,
    frame: SemanticProblemFrame,
    continuation: BoundInvestigationContinuation | None,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    available_metric_concepts: tuple[str, ...],
) -> OntologyQueryPlan | None:
    """Build a non-overlapping recovery comparison from one verified prior investigation."""

    if (
        continuation is None
        or frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != "evidence_validation"
        or continuation.target_type != "BusinessService"
        or continuation.recovery_measure_concepts != _REQUIRED_MEASURES
        or not set(_REQUIRED_MEASURES) <= set(available_metric_concepts)
        or continuation.ontology_release_digest != manifest.release_digest
        or continuation.principal_manifest_digest != manifest.manifest_digest
        or not _has_function(manifest.descriptors)
    ):
        return None
    duration = continuation.baseline_end - continuation.baseline_start
    current_end = evaluation_time.astimezone(UTC)
    current_start = current_end - duration
    if current_start < continuation.initial_observation_cutoff:
        raise LatencyRecoveryWindowPendingError("latency recovery window has not elapsed")
    target_descriptor = _descriptor(manifest.descriptors, kind="object", name="BusinessService")
    identity_property = _identity_property(target_descriptor)
    query_sides = service_resource_query_sides(manifest.descriptors)
    if identity_property is None or query_sides is None:
        return None
    path_steps = _path_steps(query_sides, manifest.descriptors)
    if path_steps is None:
        return None
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="BusinessService"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=continuation.target_value,
            ),
        ),
        as_of=current_end,
        purpose=purpose,
        limit=2,
    )
    nodes = (
        _node(
            "recovery-target",
            QueryNodeKind.OBJECT_SET,
            arguments={"definition": target_definition.model_dump(mode="json")},
            output_kind="query.table",
        ),
        _node(
            "recovery-resources",
            QueryNodeKind.TYPED_PATH,
            depends_on=("recovery-target",),
            arguments={
                "steps": list(path_steps),
                "as_of": current_end.isoformat(),
                "purpose": purpose,
                "limit": 100,
            },
            output_kind="query.table",
        ),
        _metric_node(
            "service-latency-baseline",
            scope_id="recovery-target",
            concept_id="service.latency",
            start=continuation.baseline_start,
            end=continuation.baseline_end,
        ),
        _metric_node(
            "service-latency-current",
            scope_id="recovery-target",
            concept_id="service.latency",
            start=current_start,
            end=current_end,
        ),
        _node(
            "service-latency-recovery",
            QueryNodeKind.METRIC_COMPARISON,
            depends_on=("service-latency-baseline", "service-latency-current"),
            output_kind="metric.comparison",
        ),
        _metric_node(
            "dependency-latency-baseline",
            scope_id="recovery-resources",
            concept_id="dependency.latency",
            start=continuation.baseline_start,
            end=continuation.baseline_end,
        ),
        _metric_node(
            "dependency-latency-current",
            scope_id="recovery-resources",
            concept_id="dependency.latency",
            start=current_start,
            end=current_end,
        ),
        _node(
            "dependency-latency-recovery",
            QueryNodeKind.METRIC_COMPARISON,
            depends_on=("dependency-latency-baseline", "dependency-latency-current"),
            output_kind="metric.comparison",
        ),
        _node(
            "latency-recovery-evidence",
            QueryNodeKind.FUNCTION,
            depends_on=("service-latency-recovery", "dependency-latency-recovery"),
            arguments={
                "function_name": LATENCY_RECOVERY_FUNCTION_NAME,
                "arguments": {},
                "dependency_arguments": {
                    "service-latency-recovery": "service_latency",
                    "dependency-latency-recovery": "dependency_latency",
                },
            },
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
        "output_node_ids": ["latency-recovery-evidence"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("latency-recovery-evidence",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _metric_node(
    node_id: str,
    *,
    scope_id: str,
    concept_id: str,
    start: datetime,
    end: datetime,
) -> OntologyQueryNode:
    return _node(
        node_id,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        depends_on=(scope_id,),
        arguments={
            "concept_id": concept_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        output_kind="metric.window",
    )


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


def _descriptor(
    descriptors: tuple[dict[str, Any], ...],
    *,
    kind: str,
    name: str,
) -> dict[str, Any] | None:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == kind and descriptor.get("name") == name
    )
    return selected[0] if len(selected) == 1 else None


def _identity_property(descriptor: dict[str, Any] | None) -> str | None:
    properties = descriptor.get("properties") if descriptor is not None else None
    if not isinstance(properties, Mapping):
        return None
    return next((name for name in ("name", "display_name", "id") if name in properties), None)


def _path_steps(
    query_sides: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[dict[str, object], ...] | None:
    steps: list[dict[str, object]] = []
    for query_id in query_sides:
        matches: list[tuple[dict[str, Any], Mapping[str, object]]] = []
        for descriptor in descriptors:
            sides = descriptor.get("query_sides")
            if descriptor.get("kind") != "link" or not isinstance(sides, Mapping):
                continue
            for side in sides.values():
                if isinstance(side, Mapping) and side.get("query_id") == query_id:
                    matches.append((descriptor, side))
        if len(matches) != 1:
            return None
        descriptor, side = matches[0]
        direction = side.get("direction")
        link_type = descriptor.get("name")
        endpoint = descriptor.get("to_type" if direction == "outgoing" else "from_type")
        if (
            direction not in {"outgoing", "incoming"}
            or not isinstance(link_type, str)
            or not isinstance(endpoint, str)
        ):
            return None
        steps.append(
            {
                "link_type": link_type,
                "direction": direction,
                "selector": {"kind": "object_type", "name": endpoint},
            }
        )
    return tuple(steps)


def _has_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == LATENCY_RECOVERY_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["LatencyRecoveryWindowPendingError", "compile_latency_recovery_plan"]
