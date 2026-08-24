"""Bind semantic frame candidates to immutable input and investigation identities."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import (
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_planning_models import SemanticFrameProposal


def build_semantic_frame(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    context: tuple[str, ...],
    investigation_intent: VerifiedInvestigationIntent | None = None,
) -> SemanticProblemFrame:
    """Bind a candidate frame to exact input and investigation identities."""

    input_digest = content_digest({"utterance": utterance, "context": context})
    payload = {
        "schema_version": "1.0.0",
        "operation": proposal.operation.value,
        "subject_constraints": proposal.subject_constraints,
        "measure_concepts": proposal.measure_concepts,
        "temporal_scope": proposal.temporal_scope,
        "output_shape": proposal.output_shape.value,
        "evidence_requirements": proposal.evidence_requirements,
        "unresolved_terms": proposal.unresolved_terms,
        "input_digest": input_digest,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    if investigation_intent is not None:
        payload["investigation_intent_digest"] = investigation_intent.intent_digest
    return SemanticProblemFrame(
        operation=proposal.operation,
        subject_constraints=proposal.subject_constraints,
        measure_concepts=proposal.measure_concepts,
        temporal_scope_json=canonical_json(proposal.temporal_scope),
        output_shape=proposal.output_shape.value,
        evidence_requirements=proposal.evidence_requirements,
        unresolved_terms=proposal.unresolved_terms,
        investigation_intent_digest=(
            investigation_intent.intent_digest if investigation_intent is not None else None
        ),
        input_digest=input_digest,
        frame_digest=content_digest(payload),
    )
