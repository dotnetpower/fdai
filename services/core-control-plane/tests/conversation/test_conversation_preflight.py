"""Compact conversation preflight contract and boundary tests."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.conversation_preflight import (
    ContextDependency,
    ConversationPreflightBinding,
    ConversationPreflightBoundary,
    ConversationPreflightProposal,
    OperationalSignal,
    SocialAct,
    SocialResponseNarratorBinding,
)
from fdai.core.conversation.model_observation import (
    ConversationModelObservation,
    ConversationModelResponse,
)

DIGEST = "sha256:" + ("a" * 64)


class _Model:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def preflight(self, **_kwargs: Any) -> object:
        self.calls += 1
        return self.result


class _DirectModel(_Model):
    def __init__(
        self,
        *,
        social_act: str = "greeting",
        operational_signal: str = "none",
        context_dependency: str = "none",
        confidence: float = 0.97,
    ) -> None:
        super().__init__(None)
        self.social_act = social_act
        self.operational_signal = operational_signal
        self.context_dependency = context_dependency
        self.confidence = confidence
        self.narrator_calls: list[dict[str, Any]] = []

    def preflight(self, **_kwargs: Any) -> object:
        self.calls += 1
        return {
            "social_act": self.social_act,
            "operational_signal": self.operational_signal,
            "context_dependency": self.context_dependency,
            "confidence": self.confidence,
            "execution_authority": False,
        }

    def narrate_social(self, **kwargs: Any) -> object:
        self.narrator_calls.append(kwargs)
        return {
            "locale": kwargs["locale"],
            "answer": (
                "다시 만나 뵙게 되어 반갑습니다."
                if kwargs["continued"]
                else "안녕하세요. Bragi입니다."
            ),
            "profile_digest": kwargs["direct_response_profile_digest"],
            "execution_authority": False,
        }


class _RaisingModel(_Model):
    def preflight(self, **_kwargs: Any) -> object:
        self.calls += 1
        raise RuntimeError("provider detail")


class _SequenceModel(_Model):
    def __init__(self, results: list[object]) -> None:
        super().__init__(None)
        self.results = results
        self.repairs: list[tuple[dict[str, str], ...]] = []

    def preflight(self, **kwargs: Any) -> object:
        self.calls += 1
        self.repairs.append(kwargs["schema_repair"])
        return self.results.pop(0)


def _boundary(model: _Model) -> ConversationPreflightBoundary:
    return ConversationPreflightBoundary(
        binding=ConversationPreflightBinding(
            model=model,  # type: ignore[arg-type]
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        )
    )


def test_accepts_locale_bound_direct_social_route_without_response_prose() -> None:
    model = _DirectModel()

    result = _boundary(model).classify(
        utterance="안녕",
        context=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.proposal is not None
    assert result.proposal.social_act is SocialAct.GREETING
    assert result.proposal.operational_signal is OperationalSignal.NONE
    assert result.proposal.context_dependency is ContextDependency.NONE
    assert model.calls == 1


def test_social_narrator_uses_only_typed_continuity_and_profile() -> None:
    model = _DirectModel()
    boundary = ConversationPreflightBoundary(
        binding=None,
        narrator=SocialResponseNarratorBinding(
            model=model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )

    result = boundary.narrate_social(
        utterance="또 안녕",
        locale="ko",
        social_act=SocialAct.GREETING,
        continued=True,
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.draft is not None
    assert result.draft.answer == "다시 만나 뵙게 되어 반갑습니다."
    assert result.attempted is True
    assert model.narrator_calls[0]["social_act"] == "greeting"
    assert model.narrator_calls[0]["continued"] is True
    assert "context" not in model.narrator_calls[0]


def test_social_narrator_holds_oversized_profile_before_model_call() -> None:
    model = _DirectModel()
    boundary = ConversationPreflightBoundary(
        binding=None,
        narrator=SocialResponseNarratorBinding(
            model=model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )

    result = boundary.narrate_social(
        utterance="안녕",
        locale="ko",
        social_act=SocialAct.GREETING,
        continued=False,
        direct_response_profile={"context": "x" * 20_000},
    )

    assert result.draft is None
    assert result.attempted is False
    assert model.narrator_calls == []


def test_accepts_mixed_route_without_generating_text() -> None:
    result = _boundary(
        _DirectModel(
            social_act="greeting",
            operational_signal="mixed",
        )
    ).classify(
        utterance="안녕, 현재 장애 상태를 알려줘",
        context=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.proposal is not None
    assert result.proposal.social_act is SocialAct.GREETING
    assert result.proposal.operational_signal is OperationalSignal.MIXED


def test_malformed_response_falls_through_after_one_attempt() -> None:
    observation = ConversationModelObservation(
        model="preflight-mini",
        usage={"prompt_tokens": 250, "completion_tokens": 40, "total_tokens": 290},
        trace_call={"kind": "conversation-preflight"},
    )
    model = _Model(
        ConversationModelResponse(
            proposal={"social_act": "greeting"},
            observation=observation,
        )
    )

    result = _boundary(model).classify(
        utterance="hello",
        context=(),
        locale="en",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.proposal is None
    assert result.observations == (observation, observation)
    assert result.attempted is True
    assert result.failure_kind == "malformed"
    assert model.calls == 2


def test_model_exception_falls_through_after_one_attempt() -> None:
    model = _RaisingModel(None)

    result = _boundary(model).classify(
        utterance="hello",
        context=(),
        locale="en",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.proposal is None
    assert result.attempted is True
    assert result.failure_kind == "provider_unavailable"
    assert model.calls == 1


def test_schema_repair_removes_classifier_authored_prose() -> None:
    model = _SequenceModel(
        [
            {
                "social_act": "acknowledgement",
                "operational_signal": "explicit",
                "context_dependency": "pending_decision",
                "confidence": 0.98,
                "clarification": "Should I continue?",
                "execution_authority": False,
            },
            {
                "social_act": "acknowledgement",
                "operational_signal": "explicit",
                "context_dependency": "pending_decision",
                "confidence": 0.98,
                "execution_authority": False,
            },
        ]
    )

    result = _boundary(model).classify(
        utterance="좋아, 진행해 주세요",
        context=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.proposal is not None
    assert model.calls == 2
    assert model.repairs[0] == ()
    assert model.repairs[1][0]["path"] == "proposal"


def test_classifier_contract_rejects_user_facing_response_prose() -> None:
    with pytest.raises(ValueError, match="direct_response"):
        ConversationPreflightProposal(
            social_act="greeting",
            operational_signal="none",
            context_dependency="none",
            confidence=0.99,
            direct_response={
                "locale": "en",
                "answer": "Hello.",
                "profile_digest": DIGEST,
            },
        )
