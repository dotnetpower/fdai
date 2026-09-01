"""Compile reviewed multi-endpoint relationship plans from typed frames."""

from __future__ import annotations

from datetime import datetime
from itertools import combinations
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_planning_models import QueryNodeProposal, QueryPlanProposal
from .semantic_planning_support import _build_plan
from .session import Principal

_SUPPORTED_SUBJECT_SETS = frozenset(
    {
        frozenset({"ActionType", "ResourceType", "Rule", "SignalType"}),
        frozenset({"Agent", "BusinessService", "Resource", "Workload"}),
    }
)
_SERVICE_AGENT_SUBJECTS = frozenset({"Agent", "BusinessService", "Resource", "Workload"})
_SERVICE_AGENT_STEPS = (
    ("BusinessService", "implemented_by", "outgoing", "Workload"),
    ("Workload", "workload_runs_on", "outgoing", "Resource"),
    ("Resource", "owns", "incoming", "Agent"),
)


def compile_typed_relationship_plan(
    *,
    frame: SemanticProblemFrame,
    descriptors: tuple[dict[str, Any], ...],
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
    verifier: OntologyQueryPlanVerifier,
) -> OntologyQueryPlan | None:
    """Compile endpoint and schema reads for one reviewed relationship family."""

    subjects = frozenset(frame.subject_constraints)
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != "ontology_relationships"
        or subjects not in _SUPPORTED_SUBJECT_SETS
    ):
        return None
    object_names = {
        str(descriptor["name"])
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and descriptor.get("name") in subjects
    }
    if object_names != subjects:
        return None
    if subjects == _SERVICE_AGENT_SUBJECTS:
        return _compile_service_agent_ownership_plan(
            frame=frame,
            descriptors=descriptors,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
            verifier=verifier,
        )
    relationship_pairs = _relationship_pairs(subjects, descriptors)
    if not relationship_pairs:
        return None
    nodes: list[QueryNodeProposal] = []
    output_node_ids: list[str] = []
    if subjects == frozenset({"ActionType", "ResourceType", "Rule", "SignalType"}):
        nodes.append(
            QueryNodeProposal(
                node_id="declaration-rule",
                kind=QueryNodeKind.FUNCTION,
                depends_on=(),
                arguments={
                    "function_name": "query.ontology_declaration",
                    "arguments": {
                        "kind": "object",
                        "name": "Rule",
                        "section": "detail",
                        "limit": 1,
                    },
                    "dependency_arguments": {},
                },
                output_kind="query.table",
            )
        )
    relationship_nodes = tuple(
        QueryNodeProposal(
            node_id=f"relationships-{index}",
            kind=QueryNodeKind.FUNCTION,
            depends_on=(),
            arguments={
                "function_name": "query.ontology_relationships",
                "arguments": {"object_types": list(pair), "limit": 100},
                "dependency_arguments": {},
            },
            output_kind="ontology.relationships",
        )
        for index, pair in enumerate(relationship_pairs, start=1)
    )
    nodes.extend(relationship_nodes)
    output_node_ids.extend(node.node_id for node in relationship_nodes)
    if len(nodes) > 8:
        raise ValueError("typed relationship plan exceeds the output-node bound")
    proposal = QueryPlanProposal(
        nodes=tuple(nodes),
        output_node_ids=tuple(output_node_ids),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    verifier.verify(plan, manifest=manifest)
    return plan


def _compile_service_agent_ownership_plan(
    *,
    frame: SemanticProblemFrame,
    descriptors: tuple[dict[str, Any], ...],
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
    verifier: OntologyQueryPlanVerifier,
) -> OntologyQueryPlan | None:
    declared_links = {
        str(descriptor["name"]): (
            str(descriptor["from_type"]),
            str(descriptor["to_type"]),
        )
        for descriptor in descriptors
        if descriptor.get("kind") == "link"
        and descriptor.get("name") in {step[1] for step in _SERVICE_AGENT_STEPS}
    }
    if any(
        declared_links.get(link_type)
        != ((source, target) if direction == "outgoing" else (target, source))
        for source, link_type, direction, target in _SERVICE_AGENT_STEPS
    ):
        return None
    schema_nodes = tuple(
        QueryNodeProposal(
            node_id=f"ownership-schema-{index}",
            kind=QueryNodeKind.FUNCTION,
            depends_on=(),
            arguments={
                "function_name": "query.ontology_relationships",
                "arguments": {"object_types": [source, target], "limit": 100},
                "dependency_arguments": {},
            },
            output_kind="ontology.relationships",
        )
        for index, (source, _link_type, _direction, target) in enumerate(
            _SERVICE_AGENT_STEPS,
            start=1,
        )
    )
    path_node = QueryNodeProposal(
        node_id="service-agent-paths",
        kind=QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
        depends_on=tuple(node.node_id for node in schema_nodes),
        arguments={
            "root_selector": {"kind": "object_type", "name": "BusinessService"},
            "steps": [
                {
                    "link_type": link_type,
                    "direction": direction,
                    "selector": {"kind": "object_type", "name": target},
                    "max_hops": 1,
                }
                for _source, link_type, direction, target in _SERVICE_AGENT_STEPS
            ],
            "as_of": evaluation_time.isoformat(),
            "purpose": purpose,
            "limit": 50,
        },
        output_kind="query.table",
    )
    proposal = QueryPlanProposal(
        nodes=(*schema_nodes, path_node),
        output_node_ids=(path_node.node_id,),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    verifier.verify(plan, manifest=manifest)
    return plan


def _relationship_pairs(
    subjects: frozenset[str],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, str], ...]:
    declared_pairs = {
        tuple(sorted((str(descriptor["from_type"]), str(descriptor["to_type"]))))
        for descriptor in descriptors
        if descriptor.get("kind") == "link"
        and descriptor.get("from_type") in subjects
        and descriptor.get("to_type") in subjects
    }
    return tuple(pair for pair in combinations(sorted(subjects), 2) if pair in declared_pairs)


__all__ = ["compile_typed_relationship_plan"]
