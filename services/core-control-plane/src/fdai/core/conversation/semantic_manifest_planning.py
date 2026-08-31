"""Compile declaration counts from a verified ontology manifest frame."""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.manifest_queries import ONTOLOGY_MANIFEST_FUNCTION_NAME
from fdai.shared.contracts.models import OntologyDeclarationKind

from .semantic_planning_alignment import verify_frame_plan_alignment
from .semantic_planning_models import (
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticOutputShape,
)
from .semantic_planning_support import _build_plan
from .session import Principal


def compile_ontology_manifest_count_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Build a read-only declaration count without delegating plan shape to a model."""

    if (
        frame.operation is not SemanticOperation.AGGREGATE
        or frame.output_shape != SemanticOutputShape.AGGREGATION_TABLE
        or len(frame.measure_concepts) != 1
        or frame.measure_concepts[0] != "count"
        or not frame.subject_constraints
        or not _has_manifest_function(manifest)
    ):
        return None
    try:
        kinds = tuple(OntologyDeclarationKind(value).value for value in frame.subject_constraints)
    except ValueError:
        return None
    if len(kinds) != len(set(kinds)):
        return None

    function_arguments: dict[str, object] = {}
    function_arguments["kinds"] = list(kinds)
    function_arguments["limit"] = 1000
    node_arguments: dict[str, object] = {}
    node_arguments["function_name"] = ONTOLOGY_MANIFEST_FUNCTION_NAME
    node_arguments["arguments"] = function_arguments
    node_arguments["dependency_arguments"] = {}
    manifest_node = QueryNodeProposal(
        node_id="ontology-manifest",
        kind=QueryNodeKind.FUNCTION,
        arguments=node_arguments,
        output_kind="query.table",
    )

    aggregate_arguments: dict[str, object] = {}
    aggregate_arguments["operation"] = "count"
    aggregate_arguments["group_by"] = ["kind"]
    aggregate_arguments["limit"] = 10
    aggregate_node = QueryNodeProposal(
        node_id="declaration-count",
        kind=QueryNodeKind.AGGREGATE,
        depends_on=(manifest_node.node_id,),
        arguments=aggregate_arguments,
        output_kind="query.table",
    )
    nodes: list[QueryNodeProposal] = []
    nodes.append(manifest_node)
    nodes.append(aggregate_node)
    proposal = QueryPlanProposal(
        nodes=tuple(nodes),
        output_node_ids=(aggregate_node.node_id,),
    )
    plan = _build_plan(
        proposal,
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    verified = verifier.verify(plan, manifest=manifest)
    verify_frame_plan_alignment(frame, verified, descriptors=manifest.descriptors)
    return verified


def _has_manifest_function(manifest: QueryManifest) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == ONTOLOGY_MANIFEST_FUNCTION_NAME
        for descriptor in manifest.descriptors
    )


__all__ = ["compile_ontology_manifest_count_plan"]
