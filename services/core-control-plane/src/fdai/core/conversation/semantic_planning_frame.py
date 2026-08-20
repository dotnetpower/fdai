"""Build verified semantic frames and resolve server-owned clarification context."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)


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


def resolve_incident_reference(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Resolve the incident question only when the typed frame reads that incident."""

    requirements = proposal.clarification_requirements
    if (
        requirements != (ClarificationRequirement.INCIDENT_REFERENCE,)
        or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_principal_scope_evidence_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use server-owned Resource scope for an otherwise complete evidence frame."""

    if (
        frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION
        or proposal.clarification_requirements
        not in {
            (ClarificationRequirement.SUBJECT,),
            (ClarificationRequirement.RESOURCE_IDENTITY,),
        }
        or proposal.subject_constraints not in {(), ("Resource",)}
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


__all__ = [
    "build_semantic_frame",
    "resolve_incident_reference",
    "resolve_principal_scope_evidence_subject",
]
