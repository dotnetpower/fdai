from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from fdai.core.conversation.conversation_preflight import (
    ConversationPreflightBinding,
    ConversationPreflightBoundary,
    ConversationPreflightResult,
)
from fdai.core.conversation.model_observation import (
    ConversationModelObservation,
    ConversationModelResponse,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai_service_contracts.semantic_turn import SemanticConversationModelTier

DIGEST = "sha256:" + ("a" * 64)


class _PreflightModel:
    def __init__(self, model: str) -> None:
        self.model = model
        self.calls = 0

    def preflight(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
        schema_repair: tuple[dict[str, str], ...],
        cancelled: object | None = None,
    ) -> ConversationModelResponse:
        del context, direct_response_profile, schema_repair, cancelled
        self.calls += 1
        return ConversationModelResponse(
            proposal={
                "social_act": "none",
                "operational_signal": "none",
                "context_dependency": "none",
                "knowledge_signal": "explicit",
                "general_answer": {
                    "locale": locale,
                    "answer": "블루-그린은 즉시 전환에, 카나리는 점진적 검증에 유리합니다.",
                    "profile_digest": direct_response_profile_digest,
                    "execution_authority": False,
                },
                "operational_family": "none",
                "operational_targets": [],
                "operational_facets": [],
                "confidence": 0.99,
                "authority": "candidate_only",
                "execution_authority": False,
            },
            observation=ConversationModelObservation(
                model=self.model,
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                trace_call={"kind": "conversation-preflight", "duration_ms": 10},
            ),
        )


def _boundary(t1: _PreflightModel, t2: _PreflightModel) -> ConversationPreflightBoundary:
    return ConversationPreflightBoundary(
        binding=ConversationPreflightBinding(t1, DIGEST, DIGEST, True),
        t2_binding=ConversationPreflightBinding(t2, DIGEST, DIGEST, True),
    )


def test_t2_tier_uses_the_t2_preflight_binding_for_the_general_answer() -> None:
    t1 = _PreflightModel("narrator-mini")
    t2 = _PreflightModel("gpt-5.6-sol")

    result = _boundary(t1, t2).classify(
        utterance="블루-그린 배포와 카나리 배포의 장단점을 비교해 줘.",
        context=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi", "role": "Explain."},
        conversation_model_tier=SemanticConversationModelTier.T2,
    )

    assert t1.calls == 0
    assert t2.calls == 1
    assert result.proposal is not None
    assert result.proposal.general_answer is not None
    assert result.observations[0].model == "gpt-5.6-sol"


async def test_runtime_returns_the_t2_preflight_answer_without_adaptive_stages() -> None:
    t1 = _PreflightModel("narrator-mini")
    t2 = _PreflightModel("gpt-5.6-sol")
    boundary = _boundary(t1, t2)

    class _Planner:
        def preflight(self, **kwargs: object) -> ConversationPreflightResult:
            return boundary.classify(
                utterance=cast(str, kwargs["utterance"]),
                context=(),
                locale=cast(str, kwargs["locale"]),
                direct_response_profile={"identity": "Bragi", "role": "Explain."},
                conversation_model_tier=cast(
                    SemanticConversationModelTier,
                    kwargs["conversation_model_tier"],
                ),
            )

    runtime = SemanticConversationRuntime(
        planner=cast(Any, _Planner()),
        executor=cast(Any, object()),
    )
    result = await runtime.handle(
        utterance="블루-그린 배포와 카나리 배포의 장단점을 비교해 줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        locale="ko",
        conversation_model_tier=SemanticConversationModelTier.T2,
    )

    assert result.disposition == "advisory_response"
    assert result.adaptive_answer is not None
    assert result.adaptive_answer.answer.startswith("블루-그린")
    assert t1.calls == 0
    assert t2.calls == 1
    assert result.planning.model_observations[0].model == "gpt-5.6-sol"
