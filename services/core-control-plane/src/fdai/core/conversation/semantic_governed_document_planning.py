"""Deterministic governed-document frame requirements and query-plan nodes."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticDocumentEvidenceMode,
    SemanticJudgmentProposal,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
)

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape

_REQUIREMENT_PREFIX = "governed_documents."
_NODE_ID = "governed-documents"


def apply_document_evidence_requirement(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Bind the accepted document mode without changing the primary output shape."""

    if judgment is None:
        return proposal, frame
    if judgment.document_evidence_mode is SemanticDocumentEvidenceMode.NONE:
        retained = tuple(
            value
            for value in proposal.evidence_requirements
            if not value.startswith(_REQUIREMENT_PREFIX)
        )
        if retained == proposal.evidence_requirements:
            return proposal, frame
        updated = proposal.model_copy(update={"evidence_requirements": retained})
        return updated, build_semantic_frame(updated, utterance=utterance, context=context)
    requirement = _requirement(judgment.document_evidence_mode)
    retained = tuple(
        value
        for value in proposal.evidence_requirements
        if not value.startswith(_REQUIREMENT_PREFIX)
    )
    updated = proposal.model_copy(update={"evidence_requirements": (*retained, requirement)})
    return updated, build_semantic_frame(updated, utterance=utterance, context=context)


def compile_governed_document_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Compile one document-only query from the original bounded utterance."""

    if frame.output_shape != SemanticOutputShape.GOVERNED_DOCUMENT_EXCERPTS:
        return None
    mode = document_evidence_mode(frame)
    if mode is not SemanticDocumentEvidenceMode.EXPLICIT or not _has_function(manifest):
        return None
    return _build_plan(
        frame=frame,
        utterance=utterance,
        manifest=manifest,
        verifier=verifier,
        purpose=purpose,
        mode=mode,
        existing_nodes=(),
        existing_output_node_ids=(),
    )


def append_governed_document_plan(
    plan: OntologyQueryPlan,
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Append an independent document read, or report an unavailable binding."""

    mode = document_evidence_mode(frame)
    if mode is None:
        return plan
    if frame.output_shape == SemanticOutputShape.GOVERNED_DOCUMENT_EXCERPTS:
        return plan if mode is SemanticDocumentEvidenceMode.EXPLICIT else None
    if not _has_function(manifest):
        return None
    document_nodes = tuple(
        node
        for node in plan.nodes
        if node.kind is QueryNodeKind.FUNCTION
        and node.arguments.get("function_name") == GOVERNED_DOCUMENT_FUNCTION_NAME
    )
    if len(document_nodes) > 1:
        raise ValueError("semantic plan contains multiple governed document nodes")
    if document_nodes:
        node = document_nodes[0]
        if (
            node.depends_on
            or node.node_id not in plan.output_node_ids
            or node.arguments.get("arguments")
            != {"query": utterance.strip(), "evidence_mode": mode.value}
            or node.arguments.get("dependency_arguments") != {}
        ):
            raise ValueError("existing governed document node does not match the required read")
        return plan
    if any(node.node_id == _NODE_ID for node in plan.nodes):
        raise ValueError("semantic plan already contains the governed document node")
    return _build_plan(
        frame=frame,
        utterance=utterance,
        manifest=manifest,
        verifier=verifier,
        purpose=purpose,
        mode=mode,
        existing_nodes=plan.nodes,
        existing_output_node_ids=plan.output_node_ids,
    )


def document_evidence_mode(
    frame: SemanticProblemFrame,
) -> SemanticDocumentEvidenceMode | None:
    """Return the one canonical document evidence mode encoded in a frame."""

    values = tuple(
        value.removeprefix(_REQUIREMENT_PREFIX)
        for value in getattr(frame, "evidence_requirements", ())
        if value.startswith(_REQUIREMENT_PREFIX)
    )
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("semantic frame MUST contain at most one document evidence mode")
    try:
        mode = SemanticDocumentEvidenceMode(values[0])
    except ValueError as exc:
        raise ValueError("semantic frame document evidence mode is invalid") from exc
    if mode is SemanticDocumentEvidenceMode.NONE:
        raise ValueError("semantic frame MUST omit the none document evidence mode")
    return mode


def _build_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
    mode: SemanticDocumentEvidenceMode,
    existing_nodes: tuple[OntologyQueryNode, ...],
    existing_output_node_ids: tuple[str, ...],
) -> OntologyQueryPlan:
    query = utterance.strip()
    if not query or len(query) > 20_000:
        raise ValueError("governed document search query MUST be in [1, 20000] characters")
    node = OntologyQueryNode(
        node_id=_NODE_ID,
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": GOVERNED_DOCUMENT_FUNCTION_NAME,
                "arguments": {
                    "query": query,
                    "evidence_mode": mode.value,
                },
                "dependency_arguments": {},
            }
        ),
        output_kind="query.table",
    )
    nodes = (*existing_nodes, node)
    output_node_ids = (*existing_output_node_ids, node.node_id)
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [item.model_dump(mode="json") for item in nodes],
        "output_node_ids": list(output_node_ids),
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=output_node_ids,
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _requirement(mode: SemanticDocumentEvidenceMode) -> str:
    if mode is SemanticDocumentEvidenceMode.NONE:
        raise ValueError("none document evidence mode has no frame requirement")
    return f"{_REQUIREMENT_PREFIX}{mode.value}"


def _has_function(manifest: QueryManifest) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == GOVERNED_DOCUMENT_FUNCTION_NAME
        for descriptor in manifest.descriptors
    )


__all__ = [
    "append_governed_document_plan",
    "apply_document_evidence_requirement",
    "compile_governed_document_plan",
    "document_evidence_mode",
]
