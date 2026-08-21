"""Span and manifest verification for investigation intent."""

from __future__ import annotations

import pytest
from fdai.core.conversation.semantic_investigation import (
    InvestigationIntentProposal,
    verify_investigation_intent,
)


def _span(utterance: str, text: str) -> dict[str, object]:
    start = utterance.index(text)
    return {"start": start, "end": start + len(text), "text": text}


def _descriptors() -> tuple[dict[str, object], ...]:
    return (
        {
            "kind": "object",
            "name": "BusinessService",
            "declaration_digest": "sha256:" + ("a" * 64),
        },
        {
            "kind": "object",
            "name": "Resource",
            "declaration_digest": "sha256:" + ("b" * 64),
        },
        {
            "kind": "link",
            "name": "service_depends_on_resource",
            "from_type": "BusinessService",
            "to_type": "Resource",
            "query_sides": {
                "from": {
                    "query_id": "service_depends_on_resource.outgoing",
                    "direction": "outgoing",
                },
                "to": {
                    "query_id": "service_depends_on_resource.incoming",
                    "direction": "incoming",
                },
            },
            "declaration_digest": "sha256:" + ("c" * 64),
        },
    )


def _proposal(utterance: str) -> InvestigationIntentProposal:
    return InvestigationIntentProposal.model_validate(
        {
            "operation": "explain_change",
            "entities": [
                {
                    "mention_id": "target",
                    "span": _span(utterance, "A서비스"),
                    "role": "affected_target",
                    "object_type_candidates": ["BusinessService"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "latency",
                    "span": _span(utterance, "느려졌어"),
                    "concept_id": "service.latency",
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "latency",
            "temporal_cues": [
                {
                    "cue_id": "onset",
                    "span": _span(utterance, "갑자기"),
                    "role": "onset",
                }
            ],
            "relationship_intents": [
                {
                    "relationship_id": "dependency-neighborhood",
                    "span": _span(utterance, "왜"),
                    "source_mention_id": "target",
                    "target_mention_id": None,
                    "query_side_candidates": ["service_depends_on_resource.outgoing"],
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "dependency-latency",
                    "span": _span(utterance, "왜"),
                    "relationship_id": "dependency-neighborhood",
                    "cause_measure_concept": "dependency.latency",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["resource-saturation"],
                },
                {
                    "hypothesis_id": "resource-saturation",
                    "span": _span(utterance, "왜"),
                    "relationship_id": "dependency-neighborhood",
                    "cause_measure_concept": "resource.saturation",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["dependency-latency"],
                },
            ],
            "evidence_standard": "support_and_refutation",
            "answer_shape": "diagnosis",
            "confidence": 0.91,
        }
    )


def test_korean_investigation_intent_is_span_and_manifest_grounded() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"

    verified = verify_investigation_intent(
        _proposal(utterance),
        utterance=utterance,
        descriptors=_descriptors(),
        metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
    )

    assert verified.entities[0].span.text == "A서비스"
    assert utterance[verified.entities[0].span.start : verified.entities[0].span.end] == "A서비스"
    assert verified.intent_digest.startswith("sha256:")
    assert verified.authority == "candidate_only"
    assert verified.execution_authority is False


def test_english_investigation_intent_preserves_exact_target_and_direction() -> None:
    utterance = "Why did service-example-api suddenly become slower?"
    proposal = InvestigationIntentProposal.model_validate(
        {
            "operation": "explain_change",
            "entities": [
                {
                    "mention_id": "target",
                    "span": _span(utterance, "service-example-api"),
                    "role": "affected_target",
                    "object_type_candidates": ["BusinessService"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "latency",
                    "span": _span(utterance, "slower"),
                    "concept_id": "service.latency",
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "latency",
            "temporal_cues": [
                {
                    "cue_id": "onset",
                    "span": _span(utterance, "suddenly"),
                    "role": "onset",
                }
            ],
            "relationship_intents": [
                {
                    "relationship_id": "dependency-neighborhood",
                    "span": _span(utterance, "Why"),
                    "source_mention_id": "target",
                    "target_mention_id": None,
                    "query_side_candidates": ["service_depends_on_resource.outgoing"],
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "dependency-latency",
                    "span": _span(utterance, "Why"),
                    "relationship_id": "dependency-neighborhood",
                    "cause_measure_concept": "dependency.latency",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["resource-saturation"],
                },
                {
                    "hypothesis_id": "resource-saturation",
                    "span": _span(utterance, "Why"),
                    "relationship_id": "dependency-neighborhood",
                    "cause_measure_concept": "resource.saturation",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["dependency-latency"],
                },
            ],
            "evidence_standard": "support_and_refutation",
            "answer_shape": "diagnosis",
            "confidence": 0.9,
        }
    )

    verified = verify_investigation_intent(
        proposal,
        utterance=utterance,
        descriptors=_descriptors(),
        metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
    )

    assert verified.entities[0].span.text == "service-example-api"
    assert verified.symptom_measures[0].direction.value == "increase"
    assert verified.temporal_cues[0].role.value == "onset"
    assert len(verified.hypotheses) == 2
    assert verified.execution_authority is False


def test_frame_json_schema_exposes_complete_structured_investigation_contract() -> None:
    from fdai.core.conversation.semantic_planning_models import SemanticFrameProposal

    schema = SemanticFrameProposal.model_json_schema()
    investigation_ref = schema["properties"]["investigation"]["anyOf"][0]["$ref"]
    investigation_name = investigation_ref.rsplit("/", maxsplit=1)[-1]
    investigation = schema["$defs"][investigation_name]

    assert set(investigation["required"]) >= {
        "entities",
        "symptom_measures",
        "primary_symptom_measure_id",
        "temporal_cues",
        "relationship_intents",
        "hypotheses",
        "evidence_standard",
        "answer_shape",
    }
    assert investigation["additionalProperties"] is False
    assert "investigation" in schema["required"]
    span = schema["$defs"]["IntentSourceSpan"]
    assert set(span["required"]) == {"start", "end", "text"}
    assert span["additionalProperties"] is False


def test_changed_span_text_is_rejected_before_planning() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance)
    changed = proposal.model_copy(
        update={
            "entities": (
                proposal.entities[0].model_copy(
                    update={
                        "span": proposal.entities[0].span.model_copy(update={"text": "B서비스"})
                    }
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="source span does not match"):
        verify_investigation_intent(
            changed,
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
        )


def test_unique_span_text_rebinds_an_invalid_offset_before_planning() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance)
    symptom = proposal.symptom_measures[0]
    changed = proposal.model_copy(
        update={
            "symptom_measures": (
                symptom.model_copy(
                    update={
                        "span": symptom.span.model_copy(
                            update={"start": symptom.span.start - 1, "end": symptom.span.end - 1}
                        )
                    }
                ),
            )
        }
    )

    verified = verify_investigation_intent(
        changed,
        utterance=utterance,
        descriptors=_descriptors(),
        metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
    )

    rebound = verified.symptom_measures[0].span
    assert (rebound.start, rebound.end, rebound.text) == (
        utterance.index("느려졌어"),
        utterance.index("느려졌어") + len("느려졌어"),
        "느려졌어",
    )


def test_invalid_offset_with_repeated_span_text_is_rejected_as_ambiguous() -> None:
    utterance = "왜 A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance)
    relationship = proposal.relationship_intents[0]
    changed = proposal.model_copy(
        update={
            "relationship_intents": (
                relationship.model_copy(
                    update={"span": relationship.span.model_copy(update={"start": 1, "end": 2})}
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="source span text is ambiguous"):
        verify_investigation_intent(
            changed,
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
        )


def test_unknown_metric_concept_is_rejected_before_provider_read() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"

    with pytest.raises(ValueError, match="metric concept is unavailable"):
        verify_investigation_intent(
            _proposal(utterance),
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation"),
        )


def test_investigation_without_an_affected_target_is_rejected_before_provider_read() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance)
    changed = proposal.model_copy(
        update={"entities": (proposal.entities[0].model_copy(update={"role": "scope_anchor"}),)}
    )

    with pytest.raises(ValueError, match="requires one affected target"):
        verify_investigation_intent(
            changed,
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
        )


def test_unknown_relationship_side_is_rejected_before_graph_expansion() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance)
    changed = proposal.model_copy(
        update={
            "relationship_intents": (
                proposal.relationship_intents[0].model_copy(
                    update={"query_side_candidates": ("invented_link.outgoing",)}
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="relationship side is absent"):
        verify_investigation_intent(
            changed,
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
        )


def test_relationship_direction_must_match_the_source_entity_type() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance)
    changed = proposal.model_copy(
        update={
            "relationship_intents": (
                proposal.relationship_intents[0].model_copy(
                    update={"query_side_candidates": ("service_depends_on_resource.incoming",)}
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="source type does not match"):
        verify_investigation_intent(
            changed,
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
        )


@pytest.mark.parametrize("evidence_standard", ("best_available", "complete_windows"))
def test_causal_intent_requires_support_and_refutation(evidence_standard: str) -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _proposal(utterance).model_copy(update={"evidence_standard": evidence_standard})

    with pytest.raises(ValueError, match="support and refutation"):
        verify_investigation_intent(
            proposal,
            utterance=utterance,
            descriptors=_descriptors(),
            metric_concepts=("dependency.latency", "resource.saturation", "service.latency"),
        )
