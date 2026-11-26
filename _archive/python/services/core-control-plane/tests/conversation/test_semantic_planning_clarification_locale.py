"""Server-authored clarification questions follow the operator's language."""

from __future__ import annotations

from fdai.core.conversation.semantic_planning_frame_gate import _clarification_for_frame
from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai_service_contracts.ontology_query import SemanticOperation


def _proposal() -> SemanticFrameProposal:
    return SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope={},
        output_shape=SemanticOutputShape.RESOURCE_LIST,
        evidence_requirements=(),
        unresolved_terms=("리소스 그룹", "몇 개"),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=None,
        investigation=None,
        confidence=0.9,
    )


def test_unresolved_concepts_are_clarified_in_korean_for_a_korean_turn() -> None:
    question = _clarification_for_frame(_proposal(), utterance="리소스 그룹이 몇 개야?")

    assert question == "다음 표현이 무엇을 뜻하는지 구체적으로 알려주세요: 리소스 그룹, 몇 개?"


def test_unresolved_concepts_stay_english_for_an_english_turn() -> None:
    question = _clarification_for_frame(_proposal(), utterance="How many groups?")

    assert question.startswith("Please clarify these unresolved concepts: ")
    assert question.endswith("?")
