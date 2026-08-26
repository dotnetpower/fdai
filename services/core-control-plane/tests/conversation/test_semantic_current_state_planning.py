from typing import Any

from fdai.core.conversation.semantic_current_state_planning import (
    normalize_current_state_proposal,
)
from fdai.core.conversation.semantic_planning_cascade import SemanticPlanningCascade
from fdai.core.conversation.semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai.core.conversation.session import Principal, Role
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


def test_current_state_judgment_bypasses_drifted_frame_model() -> None:
    class _UnexpectedModel:
        def propose_frame(self, **_kwargs: Any) -> object:
            raise AssertionError("canonical current-state judgment must bypass frame proposal")

        def propose_plan(self, **_kwargs: Any) -> object:
            raise AssertionError("server-owned current-state planning must bypass plan proposal")

    cascade = SemanticPlanningCascade(
        model=_UnexpectedModel(),  # type: ignore[arg-type]
        escalation_model=None,
        verifier=object(),  # type: ignore[arg-type]
        frame_builder=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        plan_builder=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
    )

    result = cascade.propose_frame(
        utterance=(
            "aks-fdai-sre-lab-krc 클러스터의 현재 상태를 확인하고, 비정상 리소스와 근거를 알려줘."
        ),
        context=(),
        descriptors=_DESCRIPTORS,
        metric_concepts=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        semantic_judgment={
            "primary_intent": "query.resource_current_state",
            "requested_facets": ("current_state", "abnormal_resources", "evidence"),
            "action_posture": "advise_only",
            "execution_authority": False,
            "confidence": 0.95,
        },
    )

    assert result is not None
    proposal, frame, investigation = result
    assert proposal.operation is SemanticOperation.SELECT
    assert proposal.output_shape is SemanticOutputShape.TARGET_CURRENT_STATE
    assert proposal.subject_constraints == ("Resource",)
    assert frame.output_shape == SemanticOutputShape.TARGET_CURRENT_STATE
    assert investigation is None
