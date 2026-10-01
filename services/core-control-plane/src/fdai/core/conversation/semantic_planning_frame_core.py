"""Bind semantic frame candidates to immutable input and investigation identities."""

from __future__ import annotations

from typing import Any, Literal

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
    investigation_intent_digest: str | None = None,
) -> SemanticProblemFrame:
    """Bind a candidate frame to exact input and investigation identities.

    ``investigation_intent_digest`` carries an earlier frame's verified identity through a
    rebuild that only rebinds judgment fields.
    """

    input_digest = content_digest({"utterance": utterance, "context": context})
    schema_version: Literal["1.0.0", "1.1.0"] = "1.1.0" if proposal.constraint_slots else "1.0.0"
    payload: dict[str, Any] = {
        "schema_version": schema_version,
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
    intent_digest = (
        investigation_intent.intent_digest
        if investigation_intent is not None
        else investigation_intent_digest
    )
    if intent_digest is not None:
        payload["investigation_intent_digest"] = intent_digest
    if proposal.constraint_slots:
        payload["constraint_slots"] = [
            slot.model_dump(mode="json", exclude_none=True) for slot in proposal.constraint_slots
        ]
    return SemanticProblemFrame(
        operation=proposal.operation,
        schema_version=schema_version,
        subject_constraints=proposal.subject_constraints,
        measure_concepts=proposal.measure_concepts,
        temporal_scope_json=canonical_json(proposal.temporal_scope),
        output_shape=proposal.output_shape.value,
        evidence_requirements=proposal.evidence_requirements,
        constraint_slots=proposal.constraint_slots,
        unresolved_terms=proposal.unresolved_terms,
        investigation_intent_digest=intent_digest,
        input_digest=input_digest,
        frame_digest=content_digest(payload),
    )
