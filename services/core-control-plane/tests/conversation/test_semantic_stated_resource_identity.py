"""A stated exact Resource identity resolves its own clarification requirement."""

from __future__ import annotations

from typing import Any

from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai.core.conversation.semantic_target_candidate_planning import (
    resolve_stated_resource_identity,
)
from fdai_service_contracts.ontology_query import SemanticOperation

_DESCRIPTORS: tuple[dict[str, Any], ...] = (
    {"kind": "object", "name": "Resource"},
    {"kind": "object", "name": "Incident"},
)
_UTTERANCE = "Summarize warning events for aks-fdai-chaos over the last 30 minutes."


def _proposal(**overrides: Any) -> SemanticFrameProposal:
    values: dict[str, Any] = {
        "operation": SemanticOperation.SELECT,
        "subject_constraints": ("Resource",),
        "measure_concepts": ("resource_event.resource_health",),
        "temporal_scope": {"kind": "historical"},
        "output_shape": SemanticOutputShape.RESOURCE_EVENT_HISTORY,
        "evidence_requirements": ("authoritative_inventory",),
        "unresolved_terms": ("resource_identity",),
        "clarification_requirements": (ClarificationRequirement.RESOURCE_IDENTITY,),
        "clarification": "Provide the exact Resource name or ID?",
        "investigation": None,
        "confidence": 0.9,
    }
    values.update(overrides)
    return SemanticFrameProposal(**values)


def test_stated_exact_identity_resolves_the_hold_outside_current_state() -> None:
    resolved = resolve_stated_resource_identity(
        _proposal(),
        utterance=_UTTERANCE,
        descriptors=_DESCRIPTORS,
    )

    assert resolved.unresolved_terms == ()
    assert resolved.clarification_requirements == ()
    assert resolved.clarification is None


def test_unnamed_target_keeps_the_hold() -> None:
    proposal = _proposal()

    resolved = resolve_stated_resource_identity(
        proposal,
        utterance="Summarize warning events over the last 30 minutes.",
        descriptors=_DESCRIPTORS,
    )

    assert resolved == proposal


def test_two_stated_targets_keep_the_hold() -> None:
    proposal = _proposal()

    resolved = resolve_stated_resource_identity(
        proposal,
        utterance="Compare aks-fdai-chaos and aks-fdai-sre-lab for warning events.",
        descriptors=_DESCRIPTORS,
    )

    assert resolved == proposal


def test_another_unresolved_term_keeps_the_hold() -> None:
    proposal = _proposal(unresolved_terms=("resource_identity", "time_range"))

    resolved = resolve_stated_resource_identity(
        proposal,
        utterance=_UTTERANCE,
        descriptors=_DESCRIPTORS,
    )

    assert resolved == proposal


def test_a_broader_clarification_requirement_keeps_the_hold() -> None:
    proposal = _proposal(
        clarification_requirements=(
            ClarificationRequirement.RESOURCE_IDENTITY,
            ClarificationRequirement.MEASURE,
        )
    )

    resolved = resolve_stated_resource_identity(
        proposal,
        utterance=_UTTERANCE,
        descriptors=_DESCRIPTORS,
    )

    assert resolved == proposal


def test_a_non_resource_subject_keeps_the_hold() -> None:
    proposal = _proposal(subject_constraints=("Incident",))

    resolved = resolve_stated_resource_identity(
        proposal,
        utterance=_UTTERANCE,
        descriptors=_DESCRIPTORS,
    )

    assert resolved == proposal
