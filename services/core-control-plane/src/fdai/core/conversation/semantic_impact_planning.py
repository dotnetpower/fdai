"""Compile exact-target service impact reads from verified frame and ontology facts."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
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

_LOGGER = logging.getLogger(__name__)
_RUNTIME_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}"
    r"(?![A-Za-z0-9_.-])"
)


def compile_target_impact_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build one exact Resource-to-BusinessService impact traversal when unambiguous."""

    if frame.output_shape != "inventory_impact":
        return None
    target_name = _exact_target_name(frame, utterance=utterance, manifest=manifest)
    path = _service_impact_path(manifest.descriptors)
    identity_property = _resource_identity_property(manifest.descriptors)
    if target_name is None or path is None or identity_property is None:
        return None
    link_types, direction = path
    as_of = evaluation_time.astimezone(UTC)
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=target_name,
            ),
        ),
        as_of=as_of,
        purpose=purpose,
        limit=2,
    )
    nodes = (
        OntologyQueryNode(
            node_id="impact-target",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json(
                {"definition": target_definition.model_dump(mode="json")}
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="impact-services",
            kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            depends_on=("impact-target",),
            arguments_json=canonical_json(
                {
                    "selector": {
                        "kind": ObjectSelectorKind.OBJECT_TYPE.value,
                        "name": "BusinessService",
                    },
                    "link_types": list(link_types),
                    "direction": direction,
                    "max_depth": len(link_types),
                    "as_of": as_of.isoformat(),
                    "purpose": purpose,
                    "limit": 100,
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
        "output_node_ids": ["impact-services"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("impact-services",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _exact_target_name(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    manifest: QueryManifest,
) -> str | None:
    return _exact_target_from_constraints(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )


def _exact_target_from_constraints(
    subject_constraints: tuple[str, ...],
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    scanned_utterance = utterance.rstrip(".!?")
    runtime_targets = tuple(match.group(0) for match in _RUNTIME_TARGET.finditer(scanned_utterance))
    if len(runtime_targets) == 1 and any(
        descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
        for descriptor in descriptors
    ):
        return runtime_targets[0]
    if runtime_targets:
        return None
    declared = {
        name.casefold()
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    folded = utterance.casefold()
    candidates = tuple(
        subject
        for subject in subject_constraints
        if subject.casefold() not in declared
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+", subject)
        if folded.count(subject.casefold()) == 1
    )
    return candidates[0] if len(candidates) == 1 else None


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


def _service_impact_path(
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, ...], str] | None:
    edges: list[tuple[str, str, str, str]] = []
    for descriptor in descriptors:
        if descriptor.get("kind") != "link":
            continue
        name = descriptor.get("name")
        from_type = descriptor.get("from_type")
        to_type = descriptor.get("to_type")
        sides = descriptor.get("query_sides")
        if (
            not isinstance(name, str)
            or not isinstance(from_type, str)
            or not isinstance(to_type, str)
        ):
            continue
        if not isinstance(sides, Mapping):
            continue
        directions = {side.get("direction") for side in sides.values() if isinstance(side, Mapping)}
        if "outgoing" in directions:
            edges.append((from_type, to_type, name, "outgoing"))
        if "incoming" in directions:
            edges.append((to_type, from_type, name, "incoming"))
    paths: list[tuple[tuple[str, ...], str]] = []
    frontier: list[tuple[str, tuple[str, ...], str, frozenset[str]]] = [
        ("Resource", (), "", frozenset({"Resource"}))
    ]
    while frontier:
        source, links, direction, visited = frontier.pop(0)
        if len(links) >= 3:
            continue
        for edge_source, edge_target, link_type, edge_direction in edges:
            if edge_source != source or edge_target in visited:
                continue
            if direction and edge_direction != direction:
                continue
            next_links = (*links, link_type)
            if edge_target == "BusinessService":
                paths.append((next_links, edge_direction))
                continue
            frontier.append((edge_target, next_links, edge_direction, visited | {edge_target}))
    paths.sort(key=lambda item: (len(item[0]), item[0], item[1]))
    if not paths:
        return None
    shortest = tuple(item for item in paths if len(item[0]) == len(paths[0][0]))
    return shortest[0] if len(shortest) == 1 else None


__all__ = [
    "compile_target_impact_plan",
]
