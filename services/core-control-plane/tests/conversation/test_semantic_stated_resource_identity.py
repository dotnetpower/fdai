"""A stated exact Resource identity resolves its own clarification requirement."""

from __future__ import annotations

from typing import Any

from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai.core.conversation.semantic_target_candidate_planning import (
    normalize_resource_list_temporal_scope,
    resolve_stated_resource_identity,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryTerms,
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


def test_resource_list_never_requires_one_exact_resource_identity() -> None:
    resolved = resolve_stated_resource_identity(
        _proposal(
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.RESOURCE_LIST,
        ),
        utterance="이 구독의 리소스를 모두 보여줘",
        descriptors=_DESCRIPTORS,
    )

    assert resolved.unresolved_terms == ()
    assert resolved.clarification_requirements == ()
    assert resolved.clarification is None


def test_resource_list_drops_model_invented_history_without_a_temporal_signal() -> None:
    registry = InventoryQueryLanguageRegistry(
        schema_version="1.1.0",
        version="1.1.0",
        default_scope="subscription",
        default_activity_lookback_seconds=604800,
        current_requires_fresh=True,
        suffixes=(),
        signals={
            "temporal": QueryTerms(
                terms=("recent", "최근"),
            )
        },
        query_kinds={},
        groupings={},
        projections={},
        scopes={},
        states={},
        operations={},
        time_units={},
    )
    proposal = _proposal(
        measure_concepts=(),
        temporal_scope={"kind": "historical"},
        output_shape=SemanticOutputShape.RESOURCE_LIST,
    )

    normalized = normalize_resource_list_temporal_scope(
        proposal,
        utterance="이 구독의 리소스를 모두 보여줘",
        inventory_query_language=registry,
    )
    historical = normalize_resource_list_temporal_scope(
        proposal,
        utterance="최근 리소스를 모두 보여줘",
        inventory_query_language=registry,
    )

    assert normalized.temporal_scope == {}
    assert historical.temporal_scope == {"kind": "historical"}


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
