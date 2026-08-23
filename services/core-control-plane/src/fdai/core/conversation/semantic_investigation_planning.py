"""Compile verified investigation intent into bounded evidence waves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)

from .semantic_investigation import (
    InvestigationEntityRole,
    InvestigationRelationshipIntent,
    VerifiedInvestigationIntent,
)


@dataclass(frozen=True, slots=True)
class InvestigationTimeWindows:
    """Server-resolved equal windows and topology cutoffs for one investigation."""

    baseline_start: datetime
    baseline_end: datetime
    current_start: datetime
    current_end: datetime
    known_at: datetime

    def __post_init__(self) -> None:
        values = (
            self.baseline_start,
            self.baseline_end,
            self.current_start,
            self.current_end,
            self.known_at,
        )
        if any(value.tzinfo is None for value in values):
            raise ValueError("investigation windows MUST be timezone-aware")
        if not self.baseline_start < self.baseline_end <= self.current_start < self.current_end:
            raise ValueError("investigation windows MUST be ordered and non-overlapping")
        if (self.baseline_end - self.baseline_start) != (self.current_end - self.current_start):
            raise ValueError("investigation baseline and current windows MUST have equal duration")
        if self.current_end > self.known_at:
            raise ValueError("investigation window MUST NOT exceed known_at")


class InvestigationClarificationRequiredError(ValueError):
    """Name one material ambiguity that must stop investigation I/O."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def compile_investigation_plan(
    intent: VerifiedInvestigationIntent,
    *,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    windows: InvestigationTimeWindows,
    purpose: str,
    problem_frame_digest: str | None = None,
) -> OntologyQueryPlan:
    """Build and verify one closed investigation DAG without model-authored nodes."""

    if purpose not in manifest.purposes:
        raise PermissionError("investigation purpose is absent from the principal manifest")
    target = _affected_target(intent)
    if len(target.object_type_candidates) != 1:
        raise InvestigationClarificationRequiredError("entity_type_ambiguous")
    target_type = target.object_type_candidates[0]
    target_descriptor = _descriptor(manifest, kind="object", name=target_type)
    identity_property = _identity_property(target_descriptor)
    relationships = {item.relationship_id: item for item in intent.relationship_intents}
    primary_measure = next(
        item
        for item in intent.symptom_measures
        if item.measure_id == intent.primary_symptom_measure_id
    )

    nodes: list[OntologyQueryNode] = []
    resolve_id = "resolve-target"
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=target_type),
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
    )
    nodes.append(
        _node(
            resolve_id,
            QueryNodeKind.OBJECT_SET,
            arguments={"definition": target_definition.model_dump(mode="json")},
            output_kind="query.table",
        )
    )
    activity_id = "change-activity"
    nodes.append(
        _node(
            activity_id,
            QueryNodeKind.FUNCTION,
            depends_on=(resolve_id,),
            arguments={
                "function_name": RESOURCE_ACTIVITY_FUNCTION_NAME,
                "arguments": {"lookback_seconds": 86_400},
                "dependency_arguments": {resolve_id: "query_result"},
            },
            output_kind="query.table",
        )
    )

    traversal_ids: dict[str, str] = {}
    for relationship in intent.relationship_intents:
        traversal_id = f"expand-{relationship.relationship_id}"
        traversal_ids[relationship.relationship_id] = traversal_id
        steps, _target_object_type = _relationship_path(
            relationship,
            manifest=manifest,
            source_type=target_type,
        )
        nodes.append(
            _node(
                traversal_id,
                QueryNodeKind.TYPED_PATH,
                depends_on=(resolve_id,),
                arguments={
                    "steps": list(steps),
                    "as_of": windows.current_end.isoformat(),
                    "purpose": purpose,
                    "limit": 100,
                },
                output_kind="query.table",
            )
        )

    symptom_baseline_id = "symptom-baseline"
    symptom_current_id = "symptom-current"
    nodes.extend(
        (
            _metric_scope_node(
                symptom_baseline_id,
                scope_id=resolve_id,
                concept_id=primary_measure.concept_id,
                start=windows.baseline_start,
                end=windows.baseline_end,
            ),
            _metric_scope_node(
                symptom_current_id,
                scope_id=resolve_id,
                concept_id=primary_measure.concept_id,
                start=windows.current_start,
                end=windows.current_end,
            ),
        )
    )
    comparison_id = "symptom-change"
    nodes.append(
        _node(
            comparison_id,
            QueryNodeKind.METRIC_COMPARISON,
            depends_on=(symptom_baseline_id, symptom_current_id),
            output_kind="metric.comparison",
        )
    )

    topology_before_id = "topology-before"
    topology_after_id = "topology-after"
    topology_diff_id = "topology-change"
    nodes.extend(
        (
            _topology_node(
                topology_before_id,
                as_of=windows.baseline_end,
                known_at=windows.known_at,
            ),
            _topology_node(
                topology_after_id,
                as_of=windows.current_end,
                known_at=windows.known_at,
            ),
            _node(
                topology_diff_id,
                QueryNodeKind.TOPOLOGY_DIFF,
                depends_on=(topology_before_id, topology_after_id),
                output_kind="topology.diff",
            ),
        )
    )

    hypothesis_outputs: list[str] = []
    for hypothesis in intent.hypotheses:
        relationship = relationships[hypothesis.relationship_id]
        cause_id = f"cause-{hypothesis.hypothesis_id}"
        result_id = f"hypothesis-{hypothesis.hypothesis_id}"
        cause_scope_id = (
            resolve_id
            if hypothesis.cause_measure_concept in {"dependency.latency", "resource.saturation"}
            else traversal_ids[relationship.relationship_id]
        )
        nodes.append(
            _metric_scope_node(
                cause_id,
                scope_id=cause_scope_id,
                concept_id=hypothesis.cause_measure_concept,
                start=windows.current_start,
                end=windows.current_end,
            )
        )
        nodes.append(
            _node(
                result_id,
                QueryNodeKind.EVIDENCE_JOIN,
                depends_on=(
                    cause_id,
                    symptom_current_id,
                    topology_diff_id,
                    comparison_id,
                ),
                arguments={
                    "feature_cutoff": windows.current_start.isoformat(),
                    "effect_direction": primary_measure.direction.value,
                    "lag_seconds": [0, 60, 300],
                    "min_samples": 4,
                    "min_abs_correlation": 0.5,
                    "competing_explanations": list(hypothesis.competing_explanations),
                },
                output_kind="causal.join",
            )
        )
        hypothesis_outputs.append(result_id)

    if len(nodes) > 16:
        raise ValueError("investigation query DAG exceeds 16 nodes")
    output_node_ids = (comparison_id, activity_id, *hypothesis_outputs)
    frame_digest = problem_frame_digest or intent.intent_digest
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": output_node_ids,
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=tuple(nodes),
        output_node_ids=output_node_ids,
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _affected_target(intent: VerifiedInvestigationIntent):  # type: ignore[no-untyped-def]
    targets = tuple(
        item for item in intent.entities if item.role is InvestigationEntityRole.AFFECTED_TARGET
    )
    if len(targets) != 1:
        raise InvestigationClarificationRequiredError("affected_target_ambiguous")
    return targets[0]


def _descriptor(
    manifest: QueryManifest,
    *,
    kind: str,
    name: str,
) -> dict[str, Any]:
    selected = tuple(
        item
        for item in manifest.descriptors
        if item.get("kind") == kind and item.get("name") == name
    )
    if len(selected) != 1:
        raise ValueError("investigation declaration is absent or ambiguous")
    return selected[0]


def _identity_property(descriptor: dict[str, Any]) -> str:
    properties = descriptor.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("investigation target has no readable properties")
    for candidate in ("name", "display_name", "id"):
        if candidate in properties:
            return candidate
    raise InvestigationClarificationRequiredError("entity_identity_property_unavailable")


def _relationship_path(
    relationship: InvestigationRelationshipIntent,
    *,
    manifest: QueryManifest,
    source_type: str,
) -> tuple[tuple[dict[str, object], ...], str]:
    current_type = source_type
    direction: str | None = None
    steps: list[dict[str, object]] = []
    for query_id in relationship.query_side_candidates:
        descriptor, side = _query_side(manifest, query_id=query_id)
        side_direction = side.get("direction")
        if side_direction not in {"outgoing", "incoming"}:
            raise ValueError("investigation relationship direction is invalid")
        if direction is not None and direction != side_direction:
            raise InvestigationClarificationRequiredError("mixed_relationship_direction")
        direction = side_direction
        expected_source = (
            descriptor.get("from_type")
            if side_direction == "outgoing"
            else descriptor.get("to_type")
        )
        expected_target = (
            descriptor.get("to_type")
            if side_direction == "outgoing"
            else descriptor.get("from_type")
        )
        if current_type != expected_source or not isinstance(expected_target, str):
            raise ValueError("investigation relationship path endpoint does not compose")
        current_type = expected_target
        steps.append(
            {
                "link_type": str(descriptor["name"]),
                "direction": side_direction,
                "selector": {
                    "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                    "name": expected_target,
                },
            }
        )
    if direction is None:
        raise ValueError("investigation relationship path is empty")
    return tuple(steps), current_type


def _query_side(
    manifest: QueryManifest,
    *,
    query_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for descriptor in manifest.descriptors:
        if descriptor.get("kind") != "link":
            continue
        sides = descriptor.get("query_sides")
        if not isinstance(sides, dict):
            continue
        for side in sides.values():
            if isinstance(side, dict) and side.get("query_id") == query_id:
                selected.append((descriptor, side))
    if len(selected) != 1:
        raise ValueError("investigation query side is absent or ambiguous")
    return selected[0]


def _metric_scope_node(
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


def _topology_node(
    node_id: str,
    *,
    as_of: datetime,
    known_at: datetime,
) -> OntologyQueryNode:
    return _node(
        node_id,
        QueryNodeKind.TOPOLOGY_AT,
        arguments={"as_of": as_of.isoformat(), "known_at": known_at.isoformat()},
        output_kind="topology.graph",
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


__all__ = [
    "InvestigationClarificationRequiredError",
    "InvestigationTimeWindows",
    "compile_investigation_plan",
]
