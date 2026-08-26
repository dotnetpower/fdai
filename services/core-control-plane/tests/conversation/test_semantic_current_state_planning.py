from fdai.core.conversation.semantic_current_state_planning import (
    normalize_current_state_proposal,
)
from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai_service_contracts.ontology_query import SemanticOperation

_DESCRIPTORS = ({"kind": "object", "name": "Resource"},)
_UTTERANCE = "aks-example-chaos 클러스터의 현재 상태를 확인하고, 비정상 리소스와 근거를 알려줘."


def _proposal(unresolved_term: str, clarification: str) -> SemanticFrameProposal:
    return SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope={},
        output_shape=SemanticOutputShape.TARGET_CURRENT_STATE,
        evidence_requirements=("authoritative_inventory",),
        unresolved_terms=(unresolved_term,),
        clarification_requirements=(ClarificationRequirement.RESOURCE_IDENTITY,),
        clarification=clarification,
        investigation=None,
        confidence=0.9,
    )


def test_exact_target_resolves_stale_identity_clarification() -> None:
    normalized = normalize_current_state_proposal(
        _proposal("resource_identity", "어떤 리소스의 정확한 이름을 조회할까요?"),
        utterance=_UTTERANCE,
        descriptors=_DESCRIPTORS,
    )

    assert normalized.unresolved_terms == ()
    assert normalized.clarification_requirements == ()
    assert normalized.clarification is None


def test_exact_target_preserves_other_unresolved_terms() -> None:
    proposal = _proposal(
        "abnormal_resource_criteria",
        "어떤 비정상 상태 기준을 적용할까요?",
    )

    normalized = normalize_current_state_proposal(
        proposal,
        utterance=_UTTERANCE,
        descriptors=_DESCRIPTORS,
    )

    assert normalized == proposal
