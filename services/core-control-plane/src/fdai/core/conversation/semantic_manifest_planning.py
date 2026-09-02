"""Compile declaration counts from a verified ontology manifest frame."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.manifest_queries import ONTOLOGY_MANIFEST_FUNCTION_NAME
from fdai.shared.contracts.models import OntologyDeclarationKind

from .semantic_planning_alignment import verify_frame_plan_alignment
from .semantic_planning_frame import build_semantic_frame
from .semantic_planning_models import (
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_support import _build_plan
from .session import Principal


def normalize_ontology_manifest_count_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Bind a validated declaration-count intent to its manifest declaration kind."""

    if (
        frame.operation is not SemanticOperation.AGGREGATE
        or frame.output_shape != SemanticOutputShape.AGGREGATION_TABLE
        or frame.unresolved_terms
        or proposal.clarification_requirements
    ):
        return proposal, frame
    declaration_kind = _declaration_kind(frame, judgment)
    if declaration_kind is None:
        return proposal, frame
    updates: dict[str, Any] = {}
    updates["subject_constraints"] = (declaration_kind.value,)
    updates["measure_concepts"] = ("count",)
    normalized = proposal.model_copy(update=updates)
    return normalized, build_semantic_frame(normalized, utterance=utterance, context=context)


def _declaration_kind(
    frame: SemanticProblemFrame,
    judgment: SemanticJudgmentProposal | None,
) -> OntologyDeclarationKind | None:
    canonical_kinds = {
        declaration_kind
        for target in (() if judgment is None else judgment.targets)
        if (declaration_kind := _as_declaration_kind(target.canonical_value)) is not None
    }
    if len(canonical_kinds) > 1:
        return None
    if canonical_kinds:
        return next(iter(canonical_kinds))
    frame_kinds = {
        declaration_kind
        for subject in frame.subject_constraints
        if (declaration_kind := _as_declaration_kind(subject)) is not None
    }
    return next(iter(frame_kinds)) if len(frame_kinds) == 1 else None


def _as_declaration_kind(value: str | None) -> OntologyDeclarationKind | None:
    if value is None:
        return None
    try:
        return OntologyDeclarationKind(value)
    except ValueError:
        if not value.endswith("Type"):
            return None
    try:
        return OntologyDeclarationKind(value.removesuffix("Type").casefold())
    except ValueError:
        return None


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
    canonical_kinds = tuple(_as_declaration_kind(value) for value in frame.subject_constraints)
    if any(kind is None for kind in canonical_kinds):
        return None
    kinds = tuple(kind.value for kind in canonical_kinds if kind is not None)
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
