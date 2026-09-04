"""Build and normalize candidate-only semantic action-draft frames."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import _facet_affirms_concept
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape

_ACTION_DRAFT_TEMPORAL_SCOPE = {
    "ActionType": {},
    "Change": {"kind": "historical"},
    "Document": {},
    "Incident": {"kind": "current"},
    "RecoveryPlan": {"kind": "current"},
    "Rule": {},
}


def build_document_draft_frame(
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a no-authority document draft frame from one exact typed judgment."""

    if (
        judgment is None
        or judgment.primary_intent != "create.document"
        or judgment.action_posture != "draft_only"
        or judgment.action_subject != "Document"
        or judgment.targets
        or set(judgment.requested_facets) != {"complete_content", "download"}
        or judgment.ambiguous
        or judgment.unresolved_terms
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.ACTION_DRAFT,
        subject_constraints=("Document",),
        measure_concepts=("complete_content", "download"),
        temporal_scope={},
        output_shape=SemanticOutputShape.ACTION_DRAFT,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _action_draft_subject_types(constraints: tuple[str, ...]) -> set[str]:
    return {
        constraint.split(":", 1)[0]
        for constraint in constraints
        if constraint.split(":", 1)[0] in _ACTION_DRAFT_TEMPORAL_SCOPE
    }


def resolve_bound_incident_action_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Bind the trusted Incident type to an otherwise subject-empty action draft."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
        or _action_draft_subject_types(proposal.subject_constraints)
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={"subject_constraints": ("Incident", *proposal.subject_constraints)}
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_semantic_judgment_action_draft(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Rebuild a candidate-only action frame from one accepted draft judgment."""

    judgment_facets = (
        {facet.replace("-", "_") for facet in judgment.requested_facets}
        if judgment is not None
        else set()
    )
    trace_axes = all(
        any(_facet_affirms_concept(facet, concept) for facet in judgment_facets)
        for concept in ("resource_type", "signal_type", "action_type", "trace")
    )
    trace_posture = "governed" in judgment_facets or bool(
        {
            "no_current_finding",
            "without_asserting_current_finding",
            "without_current_finding",
        }.intersection(judgment_facets)
    )
    if (
        judgment is not None
        and judgment.action_posture == "advise_only"
        and frame.operation is SemanticOperation.ACTION_DRAFT
        and frame.output_shape == SemanticOutputShape.ACTION_DRAFT
        and set(proposal.subject_constraints)
        == {"ActionType", "ResourceType", "Rule", "SignalType"}
        and trace_axes
        and trace_posture
    ):
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.SELECT,
                "subject_constraints": ("ActionType", "ResourceType", "Rule", "SignalType"),
                "measure_concepts": tuple(sorted(judgment_facets)),
                "temporal_scope": {},
                "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if judgment is None or judgment.action_posture != "draft_only":
        return proposal, frame
    frame_subjects = _action_draft_subject_types(proposal.subject_constraints)
    preserve_frame_subject = (
        frame.operation is SemanticOperation.ACTION_DRAFT
        and frame.output_shape == SemanticOutputShape.ACTION_DRAFT
        and frame_subjects == {judgment.action_subject}
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    subject_constraints = (
        proposal.subject_constraints if preserve_frame_subject else (judgment.action_subject,)
    )
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.ACTION_DRAFT,
            "subject_constraints": subject_constraints,
            "measure_concepts": (),
            "temporal_scope": {},
            "output_shape": SemanticOutputShape.ACTION_DRAFT,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_default_action_draft_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use ActionType for an action draft with no narrower typed subject."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
        or _action_draft_subject_types(proposal.subject_constraints)
        or proposal.subject_constraints
        or proposal.unresolved_terms
        or proposal.clarification_requirements
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={"subject_constraints": ("ActionType", *proposal.subject_constraints)}
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_action_draft_temporal_scope(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Derive an action draft's temporal scope from its canonical subject type."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
    ):
        return proposal, frame
    subject_types = _action_draft_subject_types(proposal.subject_constraints)
    if len(subject_types) != 1:
        return proposal, frame
    temporal_scope = _ACTION_DRAFT_TEMPORAL_SCOPE[next(iter(subject_types))]
    if proposal.temporal_scope == temporal_scope:
        return proposal, frame
    resolved = proposal.model_copy(update={"temporal_scope": temporal_scope})
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def canonicalize_semantic_judgment_frame_proposal(
    proposal: SemanticFrameProposal,
    *,
    judgment: Mapping[str, Any] | None,
) -> SemanticFrameProposal:
    """Preserve one accepted typed draft before validating the model frame."""

    if (
        judgment is None
        or judgment.get("action_posture") != "draft_only"
        or judgment.get("authority") != "candidate_only"
        or judgment.get("execution_authority") is not False
    ):
        return proposal
    action_subject = judgment.get("action_subject")
    if not isinstance(action_subject, str) or action_subject not in _ACTION_DRAFT_TEMPORAL_SCOPE:
        return proposal
    frame_subjects = _action_draft_subject_types(proposal.subject_constraints)
    preserve_subject = (
        frame_subjects == {action_subject}
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    return proposal.model_copy(
        update={
            "operation": SemanticOperation.ACTION_DRAFT,
            "subject_constraints": (
                proposal.subject_constraints if preserve_subject else (action_subject,)
            ),
            "measure_concepts": (),
            "temporal_scope": _ACTION_DRAFT_TEMPORAL_SCOPE[action_subject],
            "output_shape": SemanticOutputShape.ACTION_DRAFT,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
