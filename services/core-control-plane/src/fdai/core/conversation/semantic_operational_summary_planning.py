"""Build verified frames for function-backed operational summary intents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.core.ontology_platform.resource_health_queries import RESOURCE_HEALTH_FUNCTION_NAME
from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_FUNCTION_NAME
from fdai.core.ontology_platform.service_health_queries import SERVICE_HEALTH_FUNCTION_NAME
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .semantic_planning_frame import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_resource_state_planning import normalize_resource_state_proposal
from .semantic_service_health_planning import normalize_service_health_event_types

_MIN_FAST_PATH_CONFIDENCE = 0.85


def build_function_backed_summary_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Reuse a high-confidence typed function intent without another model call."""

    if (
        judgment is None
        or judgment.ambiguous
        or judgment.action_posture != "advise_only"
        or judgment.execution_authority
        or judgment.confidence < _MIN_FAST_PATH_CONFIDENCE
    ):
        return None
    available_functions = {
        descriptor["name"]
        for descriptor in descriptors
        if descriptor.get("kind") == "function" and isinstance(descriptor.get("name"), str)
    }
    intents = (judgment.primary_intent, *judgment.secondary_intents)
    if judgment.primary_intent == SERVICE_HEALTH_FUNCTION_NAME:
        if SERVICE_HEALTH_FUNCTION_NAME not in available_functions:
            return None
        proposal = _proposal(
            judgment,
            output_shape=SemanticOutputShape.SUBSCRIPTION_SERVICE_HEALTH,
            evidence_requirements=("authoritative_service_health",),
        )
        return normalize_service_health_event_types(
            proposal,
            utterance=utterance,
            context=context,
            inventory_query_language=inventory_query_language,
        )

    requested_functions = {
        intent
        for intent in intents
        if intent in {RESOURCE_STATE_FUNCTION_NAME, RESOURCE_HEALTH_FUNCTION_NAME}
    }
    if not requested_functions or not requested_functions <= available_functions:
        return None
    output_shape = (
        SemanticOutputShape.RESOURCE_STATE_LIST
        if RESOURCE_STATE_FUNCTION_NAME in requested_functions
        else SemanticOutputShape.RESOURCE_HEALTH_LIST
    )
    requirements = tuple(
        requirement
        for function_name, requirement in (
            (RESOURCE_STATE_FUNCTION_NAME, "authoritative_inventory"),
            (RESOURCE_HEALTH_FUNCTION_NAME, "authoritative_resource_health"),
        )
        if function_name in requested_functions
    )
    proposal = normalize_resource_state_proposal(
        _proposal(
            judgment,
            output_shape=output_shape,
            evidence_requirements=requirements,
        ),
        utterance=utterance,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    if not proposal.measure_concepts:
        return None
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _proposal(
    judgment: SemanticJudgmentProposal,
    *,
    output_shape: SemanticOutputShape,
    evidence_requirements: Sequence[str],
) -> SemanticFrameProposal:
    return SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope={},
        output_shape=output_shape,
        evidence_requirements=tuple(evidence_requirements),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )


__all__ = ["build_function_backed_summary_frame"]
