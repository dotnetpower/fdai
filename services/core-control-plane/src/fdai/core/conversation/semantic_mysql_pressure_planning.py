"""Compile exact MySQL pressure investigations without a model-authored query plan."""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
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
from fdai.core.ontology_platform.mysql_pressure_evidence import (
    MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
    MYSQL_PRESSURE_CONCEPTS,
    MYSQL_PRESSURE_FUNCTION_NAME,
    MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)

from .semantic_investigation import (
    InvestigationEntityRole,
    VerifiedInvestigationIntent,
)
from .semantic_investigation_planning import InvestigationTimeWindows

_DATABASE_LATENCY = "dependency.latency"


def compile_mysql_pressure_plan(
    *,
    investigation_intent: VerifiedInvestigationIntent | None,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    windows: InvestigationTimeWindows,
    purpose: str,
    problem_frame_digest: str,
    available_metric_concepts: tuple[str, ...],
) -> OntologyQueryPlan | None:
    """Build one exact MySQL pressure plan when every reviewed dependency is available."""

    if investigation_intent is None:
        return None
    primary = next(
        item
        for item in investigation_intent.symptom_measures
        if item.measure_id == investigation_intent.primary_symptom_measure_id
    )
    hypothesis_concepts = {item.cause_measure_concept for item in investigation_intent.hypotheses}
    if primary.concept_id != _DATABASE_LATENCY or hypothesis_concepts != {
        "database.mysql.cpu.utilization_pct",
        "database.mysql.query.count",
    }:
        return None
    required_metrics = set(MYSQL_PRESSURE_CONCEPTS)
    if not required_metrics.issubset(available_metric_concepts):
        return None
    _function_descriptor(manifest, MYSQL_PRESSURE_FUNCTION_NAME)
    _function_descriptor(manifest, MYSQL_DEMAND_BUNDLE_FUNCTION_NAME)
    _function_descriptor(manifest, MYSQL_SATURATION_BUNDLE_FUNCTION_NAME)
    _function_descriptor(manifest, RESOURCE_ACTIVITY_FUNCTION_NAME)
    targets = tuple(
        item
        for item in investigation_intent.entities
        if item.role is InvestigationEntityRole.AFFECTED_TARGET
    )
    if len(targets) != 1 or targets[0].object_type_candidates != ("Resource",):
        return None
    target = targets[0]
    resource_descriptor = _descriptor(manifest, kind="object", name="Resource")
    identity_property = _identity_property(resource_descriptor)
    relationship = investigation_intent.relationship_intents[0]
    steps = _relationship_steps(
        relationship.query_side_candidates,
        manifest=manifest,
        source_type="Resource",
    )
    target_id = "mysql-target"
    impact_id = "impact-services"
    activity_id = "change-activity"
    nodes: list[OntologyQueryNode] = [
        _node(
            target_id,
            QueryNodeKind.OBJECT_SET,
            arguments={
                "definition": ObjectSetDefinition(
                    selector=ObjectSelector(
                        kind=ObjectSelectorKind.OBJECT_TYPE,
                        name="Resource",
                    ),
                    predicates=(
                        ObjectPredicate(
                            property=identity_property,
                            operator=ObjectPredicateOperator.EQUALS,
                            equals=target.span.text,
                        ),
                    ),
                    as_of=windows.current_end,
                    purpose=purpose,
                    limit=2,
                ).model_dump(mode="json")
            },
            output_kind="query.table",
        ),
        _node(
            impact_id,
            QueryNodeKind.TYPED_PATH,
            depends_on=(target_id,),
            arguments={
                "steps": list(steps),
                "as_of": windows.current_end.isoformat(),
                "purpose": purpose,
                "limit": 100,
            },
            output_kind="query.table",
        ),
        _node(
            activity_id,
            QueryNodeKind.FUNCTION,
            depends_on=(target_id,),
            arguments={
                "function_name": RESOURCE_ACTIVITY_FUNCTION_NAME,
                "arguments": {"lookback_seconds": 86_400},
                "dependency_arguments": {target_id: "query_result"},
            },
            output_kind="query.table",
        ),
    ]
    dependency_arguments: dict[str, str] = {}
    for concept_id in MYSQL_PRESSURE_CONCEPTS:
        scope_id = impact_id if concept_id == _DATABASE_LATENCY else target_id
        prefix = _node_prefix(concept_id)
        for period, start, end in (
            ("baseline", windows.baseline_start, windows.baseline_end),
            ("current", windows.current_start, windows.current_end),
        ):
            node_id = f"{prefix}-{period}"
            nodes.append(
                _node(
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
            )
            dependency_arguments[node_id] = f"{_input_prefix(concept_id)}_{period}"
    demand_dependencies = {
        node_id: argument_name
        for node_id, argument_name in dependency_arguments.items()
        if argument_name.startswith("database_latency") or argument_name.startswith("mysql_queries")
    }
    saturation_dependencies = {
        node_id: argument_name
        for node_id, argument_name in dependency_arguments.items()
        if node_id not in demand_dependencies
    }
    demand_bundle_id = "mysql-demand-metric-bundle"
    saturation_bundle_id = "mysql-saturation-metric-bundle"
    nodes.append(
        _node(
            demand_bundle_id,
            QueryNodeKind.FUNCTION,
            depends_on=tuple(demand_dependencies),
            arguments={
                "function_name": MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
                "arguments": {},
                "dependency_arguments": demand_dependencies,
            },
            output_kind="query.table",
        )
    )
    nodes.append(
        _node(
            saturation_bundle_id,
            QueryNodeKind.FUNCTION,
            depends_on=tuple(saturation_dependencies),
            arguments={
                "function_name": MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
                "arguments": {},
                "dependency_arguments": saturation_dependencies,
            },
            output_kind="query.table",
        )
    )
    reducer_id = "mysql-pressure-evidence"
    nodes.append(
        _node(
            reducer_id,
            QueryNodeKind.FUNCTION,
            depends_on=(demand_bundle_id, saturation_bundle_id),
            arguments={
                "function_name": MYSQL_PRESSURE_FUNCTION_NAME,
                "arguments": {},
                "dependency_arguments": {
                    demand_bundle_id: "demand_evidence",
                    saturation_bundle_id: "saturation_evidence",
                },
            },
            output_kind="query.table",
        )
    )
    output_node_ids = (reducer_id, activity_id, impact_id)
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": problem_frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": output_node_ids,
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=problem_frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=tuple(nodes),
        output_node_ids=output_node_ids,
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _node_prefix(concept_id: str) -> str:
    return {
        "database.mysql.active_connections": "mysql-connections",
        "database.mysql.cpu.utilization_pct": "mysql-cpu",
        "database.mysql.query.count": "mysql-queries",
        "database.mysql.slow_query.count": "mysql-slow-queries",
        "dependency.latency": "database-latency",
    }[concept_id]


def _input_prefix(concept_id: str) -> str:
    return _node_prefix(concept_id).replace("-", "_")


def _descriptor(manifest: QueryManifest, *, kind: str, name: str) -> dict[str, Any]:
    selected = tuple(
        item
        for item in manifest.descriptors
        if item.get("kind") == kind and item.get("name") == name
    )
    if len(selected) != 1:
        raise ValueError("MySQL investigation declaration is absent or ambiguous")
    return selected[0]


def _function_descriptor(manifest: QueryManifest, name: str) -> None:
    _descriptor(manifest, kind="function", name=name)


def _identity_property(descriptor: dict[str, Any]) -> str:
    properties = descriptor.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("MySQL Resource has no readable properties")
    for candidate in ("name", "display_name", "id"):
        if candidate in properties:
            return candidate
    raise ValueError("MySQL Resource has no readable identity")


def _relationship_steps(
    query_ids: tuple[str, ...],
    *,
    manifest: QueryManifest,
    source_type: str,
) -> tuple[dict[str, object], ...]:
    current_type = source_type
    steps: list[dict[str, object]] = []
    for query_id in query_ids:
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for descriptor in manifest.descriptors:
            sides = descriptor.get("query_sides")
            if descriptor.get("kind") != "link" or not isinstance(sides, dict):
                continue
            for side in sides.values():
                if isinstance(side, dict) and side.get("query_id") == query_id:
                    matches.append((descriptor, side))
        if len(matches) != 1:
            raise ValueError("MySQL service-impact path is absent or ambiguous")
        descriptor, side = matches[0]
        direction = side.get("direction")
        if direction not in {"incoming", "outgoing"}:
            raise ValueError("MySQL service-impact direction is invalid")
        expected_source = descriptor.get("to_type" if direction == "incoming" else "from_type")
        target_type = descriptor.get("from_type" if direction == "incoming" else "to_type")
        if expected_source != current_type or not isinstance(target_type, str):
            raise ValueError("MySQL service-impact path does not compose")
        steps.append(
            {
                "link_type": str(descriptor["name"]),
                "direction": direction,
                "selector": {
                    "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                    "name": target_type,
                },
            }
        )
        current_type = target_type
    if current_type != "BusinessService":
        raise ValueError("MySQL service-impact path MUST end at BusinessService")
    return tuple(steps)


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


__all__ = ["compile_mysql_pressure_plan"]
