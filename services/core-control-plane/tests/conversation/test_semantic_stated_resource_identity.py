"""A stated exact Resource identity resolves its own clarification requirement."""

from __future__ import annotations

from typing import Any

from fdai.core.conversation.semantic_planning_cascade import (
    _current_state_clarification_fallback,
)
from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai.core.conversation.semantic_target_candidate_planning import (
    build_stated_resource_filter_frame,
    normalize_resource_list_temporal_scope,
    property_filter_omits_stated_relation,
    resolve_resource_target_candidates,
    resolve_stated_resource_identity,
    resource_target_candidates_apply_to_utterance,
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
    for output_shape in (
        SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST,
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
    ):
        proposal = _proposal(
            measure_concepts=(),
            temporal_scope={"kind": "historical"},
            output_shape=output_shape,
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


def test_property_filter_requires_the_stated_relation_target() -> None:
    registry = InventoryQueryLanguageRegistry(
        schema_version="1.1.0",
        version="1.1.0",
        default_scope="subscription",
        default_activity_lookback_seconds=604800,
        current_requires_fresh=True,
        suffixes=("된",),
        signals={"resource_name_relation": QueryTerms(terms=("관련", "관련된"))},
        query_kinds={},
        groupings={},
        projections={},
        scopes={},
        states={},
        operations={},
        time_units={},
    )
    incomplete = _proposal(
        subject_constraints=("Resource",),
        measure_concepts=("type",),
        output_shape=SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
    )
    complete = incomplete.model_copy(update={"subject_constraints": ("Resource", "FDAI")})

    assert property_filter_omits_stated_relation(
        incomplete,
        utterance="FDAI와 관련된 리소스 그룹",
        inventory_query_language=registry,
    )
    assert not property_filter_omits_stated_relation(
        complete,
        utterance="FDAI와 관련된 리소스 그룹",
        inventory_query_language=registry,
    )


def test_judgment_facet_builds_one_source_grounded_resource_filter() -> None:
    descriptors = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "name": {"readable": True},
                "type": {
                    "readable": True,
                    "value_groups": [
                        {
                            "id": "resource-group",
                            "terms": ["resource group", "리소스 그룹"],
                            "values": ["resource-group"],
                        }
                    ],
                },
            },
        },
    )

    result = build_stated_resource_filter_frame(
        semantic_judgment={
            "primary_intent": "query.resource_current_state",
            "requested_facets": ("resource_groups", "name_filter"),
            "targets": (
                {
                    "kind": "resource_group_name_filter",
                    "value": "FDAI",
                    "canonical_value": None,
                },
            ),
            "action_posture": "advise_only",
            "confidence": 0.95,
        },
        utterance="FDAI 관련 리소스 그룹은 뭐가 있나요?",
        context=(),
        descriptors=descriptors,
    )

    assert result is not None
    proposal, frame = result
    assert proposal.subject_constraints == ("Resource", "FDAI")
    assert proposal.measure_concepts == ("name", "type")
    assert frame.output_shape == SemanticOutputShape.PROPERTY_FILTERED_RESOURCES
    resolved_proposal, resolved_frame = resolve_resource_target_candidates(
        proposal,
        frame,
        utterance="FDAI 관련 리소스 그룹은 뭐가 있나요?",
        context=(),
        descriptors=descriptors,
    )
    assert resolved_proposal == proposal
    assert resolved_frame == frame
    assert not resource_target_candidates_apply_to_utterance(
        frame,
        utterance="FDAI 관련 리소스 그룹은 뭐가 있나요?",
        descriptors=descriptors,
    )


def test_current_state_fallback_does_not_narrow_a_typed_collection() -> None:
    result = _current_state_clarification_fallback(
        semantic_judgment={
            "primary_intent": "query.resource_current_state",
            "requested_facets": ("resource_current_state",),
            "targets": (
                {"kind": "resource_state", "value": "stopped"},
                {"kind": "resource_state", "value": "failed"},
            ),
        },
        utterance="상태별로 리소스를 보여주세요.",
        context=(),
        descriptors=_DESCRIPTORS,
        confidence=0.95,
    )

    assert result is None


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
