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
from fdai.core.ontology_platform.declaration_queries import (
    ONTOLOGY_DECLARATION_FUNCTION_NAME,
)
from fdai.core.ontology_platform.manifest_queries import ONTOLOGY_MANIFEST_FUNCTION_NAME
from fdai.core.ontology_platform.relationship_queries import (
    ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
)
from fdai.shared.contracts.models import OntologyDeclarationKind

from .semantic_planning_alignment import (
    DECLARATION_SECTIONS_BY_MEASURE,
    verify_frame_plan_alignment,
)
from .semantic_planning_frame import build_semantic_frame
from .semantic_planning_models import (
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_support import _build_plan
from .session import Principal


def build_ontology_schema_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build an exact schema frame from one accepted no-authority judgment."""

    if (
        judgment is None
        or judgment.ambiguous
        or judgment.action_posture != "advise_only"
        or judgment.execution_authority
        or judgment.secondary_intents
    ):
        return None
    available_functions = {
        descriptor.get("name") for descriptor in descriptors if descriptor.get("kind") == "function"
    }
    requests_declaration_count = any(
        facet == "count" or facet.endswith("_count") for facet in judgment.requested_facets
    )
    declaration_kinds = _declaration_kinds_from_judgment(judgment)
    if requests_declaration_count and _is_schema_read_intent(judgment.primary_intent):
        if (
            ONTOLOGY_MANIFEST_FUNCTION_NAME not in available_functions
            or len(declaration_kinds) != 1
        ):
            return None
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.AGGREGATE,
            subject_constraints=(next(iter(declaration_kinds)).value,),
            measure_concepts=("count",),
            temporal_scope={},
            output_shape=SemanticOutputShape.AGGREGATION_TABLE,
            evidence_requirements=(),
            unresolved_terms=(),
            clarification_requirements=(),
            clarification=None,
            investigation=None,
            confidence=judgment.confidence,
        )
        return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)
    normalized_facets = {
        facet.replace("_", "").replace("-", "").casefold() for facet in judgment.requested_facets
    }
    declaration_kind_facet_requested = any(
        f"{declaration_kind.value}type" in normalized_facets
        or f"{declaration_kind.value}types" in normalized_facets
        for declaration_kind in declaration_kinds
    )
    plural_kind_requested = any(
        f"{declaration_kind.value}types" in normalized_facets
        for declaration_kind in declaration_kinds
    )
    readable_facets = frozenset({"available", "queryable", "readable"})
    readable_kind_facets = {
        f"{readable}{declaration_kind.value}types"
        for declaration_kind in declaration_kinds
        for readable in readable_facets
    }
    compact_facets = (
        readable_facets
        | readable_kind_facets
        | {f"{declaration_kind.value}types" for declaration_kind in declaration_kinds}
    )
    compact_readable_request = normalized_facets <= compact_facets and (
        bool(readable_kind_facets.intersection(normalized_facets))
        or (plural_kind_requested and bool(readable_facets.intersection(normalized_facets)))
    )
    requests_visible_manifest = (
        compact_readable_request
        or {"queryable", "visible", "currentscope"} <= normalized_facets
        or (
            {"list", "currentscope"} <= normalized_facets
            and any(facet.endswith("typevisibility") for facet in normalized_facets)
        )
        or (
            declaration_kind_facet_requested
            and {"list", "visible", "currentscope"} <= normalized_facets
        )
        or (plural_kind_requested and {"visible", "currentscope"} <= normalized_facets)
        or (
            plural_kind_requested
            and (
                {"visibletooperator", "currentscope"} <= normalized_facets
                or "visibleincurrentscope" in normalized_facets
            )
        )
    )
    if (
        _is_schema_read_intent(judgment.primary_intent)
        and not judgment.targets
        and len(declaration_kinds) == 1
        and requests_visible_manifest
    ):
        if ONTOLOGY_MANIFEST_FUNCTION_NAME not in available_functions:
            return None
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.SELECT,
            subject_constraints=(next(iter(declaration_kinds)).value,),
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.ONTOLOGY_MANIFEST,
            evidence_requirements=("principal_manifest_evidence",),
            unresolved_terms=(),
            clarification_requirements=(),
            clarification=None,
            investigation=None,
            confidence=judgment.confidence,
        )
        return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)
    if judgment.primary_intent != ONTOLOGY_DECLARATION_FUNCTION_NAME:
        return None
    declared_subjects = schema_subjects_from_judgment(judgment, descriptors=descriptors)
    if ONTOLOGY_DECLARATION_FUNCTION_NAME not in available_functions or len(declared_subjects) != 1:
        return None
    measures = tuple(
        measure
        for measure in DECLARATION_SECTIONS_BY_MEASURE
        if measure in judgment.requested_facets
    )
    if not measures:
        measures = ("declaration_detail",)
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=(next(iter(declared_subjects)),),
        measure_concepts=measures,
        temporal_scope={},
        output_shape=SemanticOutputShape.ONTOLOGY_DECLARATION,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def schema_subjects_from_judgment(
    judgment: SemanticJudgmentProposal,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> set[str]:
    """Resolve one schema subject only from typed targets or facets and supplied descriptors."""

    declared_subjects = {
        target.canonical_value
        for target in judgment.targets
        if target.canonical_value is not None
        and any(
            descriptor.get("kind") in {"action", "link", "object"}
            and descriptor.get("name") == target.canonical_value
            for descriptor in descriptors
        )
    }
    if declared_subjects:
        return {subject for subject in declared_subjects if subject is not None}
    normalized_facets = {
        facet.replace("_", "").replace("-", "").casefold() for facet in judgment.requested_facets
    }
    descriptor_names = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") in {"action", "link", "object"}
        if isinstance((name := descriptor.get("name")), str)
    }
    exact_subjects = {name for name in descriptor_names if name.casefold() in normalized_facets}
    if exact_subjects:
        return exact_subjects
    return {
        name
        for name in descriptor_names
        if any(facet.startswith(name.casefold()) for facet in normalized_facets)
    }


def _declaration_kinds_from_judgment(
    judgment: SemanticJudgmentProposal,
) -> set[OntologyDeclarationKind]:
    target_kinds = {
        declaration_kind
        for target in judgment.targets
        if (declaration_kind := _as_declaration_kind(target.canonical_value)) is not None
    }
    normalized_facets = {
        facet.replace("_", "").replace("-", "").casefold() for facet in judgment.requested_facets
    }
    facet_kinds = {
        declaration_kind
        for declaration_kind in OntologyDeclarationKind
        if any(f"{declaration_kind.value}type" in facet for facet in normalized_facets)
    }
    return target_kinds | facet_kinds


def _is_schema_read_intent(primary_intent: str) -> bool:
    return (
        primary_intent == ONTOLOGY_MANIFEST_FUNCTION_NAME
        or primary_intent == ONTOLOGY_DECLARATION_FUNCTION_NAME
        or primary_intent == ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME
    )


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


def compile_ontology_manifest_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Build a read-only principal manifest list without model plan fallback."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.ONTOLOGY_MANIFEST
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
    node = QueryNodeProposal(
        node_id="manifest",
        kind=QueryNodeKind.FUNCTION,
        arguments={
            "function_name": ONTOLOGY_MANIFEST_FUNCTION_NAME,
            "arguments": {"kinds": list(kinds), "limit": 1000},
            "dependency_arguments": {},
        },
        output_kind="query.table",
    )
    plan = _build_plan(
        QueryPlanProposal(nodes=(node,), output_node_ids=(node.node_id,)),
        frame=frame,
        manifest=manifest,
        principal=principal,
        purpose=purpose,
        evaluation_time=evaluation_time,
    )
    verified = verifier.verify(plan, manifest=manifest)
    verify_frame_plan_alignment(frame, verified, descriptors=manifest.descriptors)
    return verified


def compile_ontology_declaration_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan | None:
    """Build exact declaration reads without delegating closed arguments to a model."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.ONTOLOGY_DECLARATION
        or len(frame.subject_constraints) != 1
        or not frame.measure_concepts
        or not _has_function(manifest, ONTOLOGY_DECLARATION_FUNCTION_NAME)
    ):
        return None
    subject = frame.subject_constraints[0]
    declaration_kinds = {
        descriptor.get("kind")
        for descriptor in manifest.descriptors
        if descriptor.get("name") == subject
        and descriptor.get("kind") in {"action", "link", "object"}
    }
    if len(declaration_kinds) != 1:
        return None
    sections = {DECLARATION_SECTIONS_BY_MEASURE.get(measure) for measure in frame.measure_concepts}
    if None in sections or not sections:
        return None
    declaration_kind = next(iter(declaration_kinds))
    nodes = tuple(
        QueryNodeProposal(
            node_id=f"ontology-declaration-{section}",
            kind=QueryNodeKind.FUNCTION,
            arguments={
                "function_name": ONTOLOGY_DECLARATION_FUNCTION_NAME,
                "arguments": {
                    "kind": declaration_kind,
                    "name": subject,
                    "section": section,
                    "limit": 100,
                },
                "dependency_arguments": {},
            },
            output_kind="query.table",
        )
        for section in sorted(value for value in sections if value is not None)
    )
    proposal = QueryPlanProposal(
        nodes=nodes,
        output_node_ids=tuple(node.node_id for node in nodes),
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
    return _has_function(manifest, ONTOLOGY_MANIFEST_FUNCTION_NAME)


def _has_function(manifest: QueryManifest, function_name: str) -> bool:
    return any(
        descriptor.get("kind") == "function" and descriptor.get("name") == function_name
        for descriptor in manifest.descriptors
    )
