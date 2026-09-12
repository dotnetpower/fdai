"""Compact conversation preflight contract and boundary tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from fdai.core.conversation.conversation_preflight import (
    ContextDependency,
    ConversationPreflightBinding,
    ConversationPreflightBoundary,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    GeneralKnowledgeDraft,
    GeneralKnowledgeSignal,
    OperationalPreflightFamily,
    OperationalSignal,
    OperationalWindowMode,
    SocialAct,
    SocialResponseNarratorBinding,
    operational_target_is_generic,
    preflight_operational_judgment,
    preflight_selects_general_knowledge,
)
from fdai.core.conversation.model_observation import (
    ConversationModelObservation,
    ConversationModelResponse,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticTarget

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


class _StrictLegacyModel:
    def __init__(self) -> None:
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
    ) -> object:
        del (
            utterance,
            context,
            locale,
            direct_response_profile,
            direct_response_profile_digest,
            schema_repair,
        )
        self.calls += 1
        return {
            "social_act": "greeting",
            "operational_signal": "none",
            "context_dependency": "none",
            "confidence": 0.99,
            "execution_authority": False,
        }


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


def test_legacy_preflight_provider_is_not_passed_cancellation() -> None:
    model = _StrictLegacyModel()
    boundary = ConversationPreflightBoundary(
        binding=ConversationPreflightBinding(
            model=model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        )
    )

    result = boundary.classify(
        utterance="hello",
        context=(),
        locale="en",
        direct_response_profile={"identity": "Bragi"},
        cancelled=asyncio.Event(),
    )

    assert result.proposal is not None
    assert result.failure_kind is None
    assert model.calls == 1


@pytest.mark.parametrize(
    ("confidence", "selected"),
    [(0.9, True), (0.89, False)],
)
def test_general_knowledge_route_requires_promotion_confidence(
    confidence: float,
    selected: bool,
) -> None:
    utterance = "Compare blue-green and canary."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.NONE,
        context_dependency=ContextDependency.NONE,
        knowledge_signal=GeneralKnowledgeSignal.EXPLICIT,
        general_answer=GeneralKnowledgeDraft(
            locale="en",
            answer="Blue-green swaps environments; canary increases exposure gradually.",
            profile_digest=DIGEST,
        ),
        confidence=confidence,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
        direct_response_profile_digest=DIGEST,
    )

    assert preflight_selects_general_knowledge(result, utterance=utterance, locale="en") is selected


def test_general_knowledge_route_requires_current_input_and_model_provenance() -> None:
    utterance = "Compare blue-green and canary."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.NONE,
        context_dependency=ContextDependency.NONE,
        knowledge_signal=GeneralKnowledgeSignal.EXPLICIT,
        general_answer=GeneralKnowledgeDraft(
            locale="en",
            answer="Blue-green swaps environments; canary increases exposure gradually.",
            profile_digest=DIGEST,
        ),
        confidence=0.99,
    )
    valid = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
        direct_response_profile_digest=DIGEST,
    )

    assert preflight_selects_general_knowledge(valid, utterance=utterance, locale="en")
    assert not preflight_selects_general_knowledge(
        replace(valid, input_digest=content_digest({"utterance": "different"})),
        utterance=utterance,
        locale="en",
    )
    assert not preflight_selects_general_knowledge(
        replace(valid, prompt_digest=None),
        utterance=utterance,
        locale="en",
    )
    assert not preflight_selects_general_knowledge(valid, utterance=utterance, locale="ko")


def test_boundary_accepts_one_bounded_general_answer_with_the_route() -> None:
    utterance = "블루-그린과 카나리 배포를 비교해 줘."
    profile = {"identity": "Bragi", "role": "Narrate without authority."}
    profile_digest = content_digest(profile)
    model = _Model(
        {
            "social_act": "none",
            "knowledge_signal": "explicit",
            "general_answer": {
                "locale": "ko",
                "answer": (
                    "블루-그린은 환경을 한 번에 전환하고 카나리는 트래픽을 점진적으로 확대합니다."
                ),
                "profile_digest": profile_digest,
                "execution_authority": False,
            },
            "operational_signal": "none",
            "context_dependency": "none",
            "confidence": 0.99,
            "execution_authority": False,
        }
    )

    result = _boundary(model).classify(
        utterance=utterance,
        context=(),
        locale="ko",
        direct_response_profile=profile,
    )

    assert preflight_selects_general_knowledge(result, utterance=utterance, locale="ko")
    assert result.proposal is not None
    assert result.proposal.general_answer is not None
    assert result.proposal.general_answer.answer.startswith("블루-그린")
    assert model.calls == 1


def test_mixed_social_and_knowledge_route_does_not_publish_a_preflight_answer() -> None:
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.GREETING,
        operational_signal=OperationalSignal.NONE,
        context_dependency=ContextDependency.NONE,
        knowledge_signal=GeneralKnowledgeSignal.EXPLICIT,
        confidence=0.99,
    )

    assert proposal.general_answer is None
    assert not preflight_selects_general_knowledge(
        ConversationPreflightResult(proposal=proposal, attempted=True),
        utterance="Hello, compare blue-green and canary.",
        locale="en",
    )


def test_general_knowledge_draft_enforces_korean_locale_quality() -> None:
    with pytest.raises(ValueError, match="polite honorific"):
        GeneralKnowledgeDraft(
            locale="ko",
            answer="This is not Korean.",
            profile_digest=DIGEST,
        )


def test_general_knowledge_draft_allows_technical_identifiers() -> None:
    draft = GeneralKnowledgeDraft(
        locale="en",
        answer="C#, Node.js, and snake_case use different identifier conventions.",
        profile_digest=DIGEST,
    )

    assert "C#" in draft.answer
    assert "Node.js" in draft.answer
    assert "snake_case" in draft.answer


def test_korean_general_knowledge_allows_dotted_technical_identifiers() -> None:
    draft = GeneralKnowledgeDraft(
        locale="ko",
        answer="Node.js와 C#을 비교해 드립니다.",
        profile_digest=DIGEST,
    )

    assert draft.answer == "Node.js와 C#을 비교해 드립니다."


def test_general_knowledge_draft_rejects_bare_domains() -> None:
    with pytest.raises(ValueError, match="MUST NOT contain links"):
        GeneralKnowledgeDraft(
            locale="en",
            answer="See attacker.example for details.",
            profile_digest=DIGEST,
        )


@pytest.mark.parametrize(
    "answer",
    [
        "I verified the current production environment is healthy.",
        "Your current cluster is running normally.",
        "Restart the current production service now.",
        "The live deployment was restarted successfully.",
        "The service is currently healthy.",
        "The service was restarted successfully.",
        "Our service currently runs in production.",
        "The production service currently is healthy.",
        "Deploy to production now.",
        "Restart the service in production now.",
        "It is healthy in production.",
        "The cluster looks healthy in production.",
        "The gateway is healthy.",
        "It restarted successfully.",
        "The gateway restarted successfully.",
        "The backend deployed successfully.",
        "The database restarted successfully.",
        "The pod restarted successfully.",
        "Your production database contains 42 customer records.",
        "Your current subscription contains 42 resources.",
        "Your resource group contains 42 resources.",
        "The prod subscription contains 42 resources.",
        "Subscription Contoso contains 42 resources.",
        "Subscription Contoso East contains forty-two resources.",
        "Resource group prod east has many resources.",
        "The Contoso East resource group contains forty-two resources.",
        "The Contoso (East) resource group contains forty-two resources.",
        "The 운영 resource group contains forty-two resources.",
        "Subscription Contoso runs 42 services.",
        "Subscription ASP.NET contains 42 resources.",
        "Subscription 운영.동부 runs 42 services.",
        "Resource group prod is running many services.",
        "The subscription includes forty-two resources.",
        "제가 현재 운영 환경을 확인했습니다.",
        "현재 프로덕션 서비스는 정상입니다.",
        "현재 운영 서비스를 재시작하세요.",
        "서비스가 현재 정상입니다.",
        "서비스가 재시작됐습니다.",
        "서비스는 운영 환경에서 정상입니다.",
        "프로덕션은 정상입니다.",
        "게이트웨이는 정상입니다.",
        "프로덕션 데이터베이스에는 고객 레코드 42개가 있습니다.",
        "현재 구독에는 리소스 42개가 있습니다.",
        "해당 리소스 그룹에는 리소스 42개가 있습니다.",
        "prod 구독에는 리소스 42개가 있습니다.",
        "리소스 그룹 rg-prod에는 리소스 42개가 있습니다.",
        "구독 Contoso East에는 리소스 마흔두 개가 있습니다.",
        "리소스 그룹 prod east에는 여러 리소스가 있습니다.",
        "Contoso East 구독에는 리소스 마흔두 개가 있습니다.",
        "Contoso (East) 구독에는 리소스 마흔두 개가 있습니다.",
    ],
)
def test_general_knowledge_draft_rejects_operational_claims(answer: str) -> None:
    with pytest.raises(ValueError, match="MUST NOT claim operational observation"):
        GeneralKnowledgeDraft(
            locale="ko" if answer.endswith(("습니다.", "세요.")) else "en",
            answer=answer,
            profile_digest=DIGEST,
        )


def test_general_knowledge_draft_allows_conceptual_health_explanation() -> None:
    draft = GeneralKnowledgeDraft(
        locale="en",
        answer="A liveness probe checks whether a container is healthy enough to keep running.",
        profile_digest=DIGEST,
    )

    assert draft.answer.startswith("A liveness probe")


@pytest.mark.parametrize(
    "answer",
    [
        "Current caching best practices favor bounded retention.",
        "Production deployment strategies include blue-green and canary.",
    ],
)
def test_general_knowledge_draft_allows_conceptual_scope_terms(answer: str) -> None:
    draft = GeneralKnowledgeDraft(
        locale="en",
        answer=answer,
        profile_digest=DIGEST,
    )

    assert draft.answer == answer


def test_general_knowledge_draft_does_not_correlate_unrelated_sentences() -> None:
    draft = GeneralKnowledgeDraft(
        locale="en",
        answer="A subscription is a billing boundary. Containers run services.",
        profile_digest=DIGEST,
    )

    assert draft.answer.endswith("Containers run services.")


@pytest.mark.parametrize("domain", ["attacker.rs", "attacker.md"])
def test_general_knowledge_draft_rejects_domain_with_technical_suffix(domain: str) -> None:
    with pytest.raises(ValueError, match="MUST NOT contain links"):
        GeneralKnowledgeDraft(
            locale="en",
            answer=f"See {domain} for details.",
            profile_digest=DIGEST,
        )


def test_general_knowledge_draft_allows_backticked_filename() -> None:
    draft = GeneralKnowledgeDraft(
        locale="en",
        answer="Configure the example in `settings.py`.",
        profile_digest=DIGEST,
    )

    assert "`settings.py`" in draft.answer


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


def test_promotes_source_grounded_operational_family_to_candidate_judgment() -> None:
    utterance = "Compare narrator-gpt-5-4-mini configuration changes for the last hour."
    target = "narrator-gpt-5-4-mini"
    start = utterance.index(target)
    time_value = "last hour"
    time_start = utterance.index(time_value)
    result = ConversationPreflightResult(
        proposal=ConversationPreflightProposal(
            social_act=SocialAct.NONE,
            operational_signal=OperationalSignal.EXPLICIT,
            context_dependency=ContextDependency.NONE,
            operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
            operational_window=OperationalWindowMode.PAST_HOUR,
            operational_targets=(
                SemanticTarget(
                    kind="resource",
                    value=target,
                    canonical_value="Resource.name",
                    source_start=start,
                    source_end=start + len(target),
                ),
                SemanticTarget(
                    kind="time_range",
                    value=time_value,
                    canonical_value="duration.PT1H",
                    source_start=time_start,
                    source_end=time_start + len(time_value),
                ),
            ),
            operational_facets=("configuration_changes",),
            confidence=0.99,
        ),
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=None,
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )
    result = replace(
        result,
        proposal_digest=content_digest(result.proposal.model_dump(mode="json")),
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.resource_configuration_changes"
    assert judgment.targets == result.proposal.operational_targets
    assert judgment.execution_authority is False


@pytest.mark.parametrize(
    ("utterance", "targets", "facets", "expected_intent"),
    (
        (
            "aks 목록",
            (("resource_type_filter", "aks"),),
            ("resource_collection", "list"),
            "query.contextual_resources",
        ),
        (
            "db 목록",
            (("resource_type_filter", "db"),),
            ("resource_collection", "list"),
            "query.contextual_resources",
        ),
        (
            "배포된 llm 모델이 뭐야",
            (("resource_type_filter", "배포된 llm 모델"),),
            ("resource_collection", "list"),
            "query.contextual_resources",
        ),
        (
            "실행중인 mssql 서버 목록",
            (
                ("resource_type_filter", "mssql 서버"),
                ("resource_state_filter", "실행중인"),
            ),
            ("resource_collection", "list", "current_state"),
            "query.resource_state_inventory",
        ),
        (
            "지금 fdai 가 포함된 리소스 그룹은?",
            (
                ("resource_type_filter", "리소스 그룹"),
                ("resource_name_filter", "fdai"),
            ),
            ("resource_collection", "list", "name_filter"),
            "query.contextual_resources",
        ),
    ),
)
def test_promotes_resource_collection_without_a_second_judgment(
    utterance: str,
    targets: tuple[tuple[str, str], ...],
    facets: tuple[str, ...],
    expected_intent: str,
) -> None:
    operational_targets = tuple(
        SemanticTarget(
            kind=kind,
            value=value,
            source_start=utterance.index(value),
            source_end=utterance.index(value) + len(value),
        )
        for kind, value in targets
    )
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_COLLECTION,
        operational_targets=operational_targets,
        operational_facets=facets,
        confidence=0.98,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == expected_intent
    assert judgment.targets == operational_targets
    assert judgment.execution_authority is False


def test_resource_collection_derives_name_filter_facet_from_typed_target() -> None:
    utterance = "지금 fdai 가 포함된 리소스 그룹은?"
    targets = tuple(
        SemanticTarget(
            kind=kind,
            value=value,
            source_start=utterance.index(value),
            source_end=utterance.index(value) + len(value),
        )
        for kind, value in (
            ("resource_type_filter", "리소스 그룹"),
            ("resource_name_filter", "fdai"),
        )
    )
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_COLLECTION,
        operational_targets=targets,
        operational_facets=("resource_collection", "list"),
        confidence=0.98,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.contextual_resources"
    assert judgment.targets == targets
    assert judgment.requested_facets == ("resource_collection", "list", "name_filter")


@pytest.mark.parametrize(
    ("utterance", "kind", "value", "alias", "canonical"),
    (
        (
            "지금 fdai 가 포함된 리소스 그룹은?",
            "resource_name_filter",
            "fdai",
            "resource_name_filter",
            "name_filter",
        ),
        (
            "실행중인 mssql 서버 목록",
            "resource_state_filter",
            "실행중인",
            "resource_state_filter",
            "current_state",
        ),
    ),
)
def test_resource_collection_canonicalizes_typed_filter_facet_aliases(
    utterance: str,
    kind: str,
    value: str,
    alias: str,
    canonical: str,
) -> None:
    targets = (
        SemanticTarget(
            kind="resource_type_filter",
            value="리소스 그룹" if kind == "resource_name_filter" else "mssql 서버",
            source_start=utterance.index(
                "리소스 그룹" if kind == "resource_name_filter" else "mssql 서버"
            ),
            source_end=utterance.index(
                "리소스 그룹" if kind == "resource_name_filter" else "mssql 서버"
            )
            + len("리소스 그룹" if kind == "resource_name_filter" else "mssql 서버"),
        ),
        SemanticTarget(
            kind=kind,
            value=value,
            source_start=utterance.index(value),
            source_end=utterance.index(value) + len(value),
        ),
    )
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_COLLECTION,
        operational_targets=targets,
        operational_facets=("resource_collection", "list", alias),
        confidence=0.98,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert canonical in judgment.requested_facets
    assert alias not in judgment.requested_facets


def test_promotes_exact_resource_current_state_without_collection_substitution() -> None:
    utterance = "aks-example-cluster 의 상태"
    target_value = "aks-example-cluster"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CURRENT_STATE,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=target_value,
                source_start=0,
                source_end=len(target_value),
            ),
        ),
        operational_facets=("current_state",),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.resource_current_state"
    assert judgment.targets[0].value == target_value
    assert judgment.targets[0].canonical_value == "Resource.name"
    assert judgment.requested_facets == ("current_state",)


@pytest.mark.parametrize(
    ("family", "facets", "expected_intent"),
    (
        (
            OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
            ("subscription",),
            "query.subscription_scope_identity",
        ),
        (
            OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH,
            ("service_health",),
            "query.subscription_service_health",
        ),
    ),
)
def test_promotes_targetless_subscription_family_without_full_judgment(
    family: OperationalPreflightFamily,
    facets: tuple[str, ...],
    expected_intent: str,
) -> None:
    utterance = "구독 정보 알려줘"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=family,
        operational_targets=(),
        operational_facets=facets,
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == expected_intent
    assert judgment.targets == ()
    assert judgment.requested_facets == facets
    assert judgment.execution_authority is False


def test_inventory_document_derives_complete_download_facets() -> None:
    utterance = "구독에 배포된 리소스 상세 정보를 문서화하자."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.INVENTORY_DOCUMENT,
        operational_targets=(),
        operational_facets=("resource_inventory", "subscription"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "create.document"
    assert judgment.targets == ()
    assert judgment.requested_facets == (
        "resource_inventory",
        "subscription",
        "complete_content",
        "download",
    )


@pytest.mark.parametrize(
    ("utterance", "family", "targets", "facets", "expected_intent"),
    (
        (
            "구독에 배포된 GPT 리소스의 변경이 있는지 확인해보자.",
            OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
            (("resource_type_filter", "GPT 리소스"),),
            ("configuration_changes", "default_recent_window", "potential_issues"),
            "query.resource_configuration_changes",
        ),
        (
            "SRE-AppGW-01 뒤의 Client가 갑자기 느립니다.",
            OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
            (("resource", "SRE-AppGW-01"),),
            (
                "application_gateway",
                "backend",
                "configuration_changes",
                "default_recent_window",
                "latency",
            ),
            "query.gateway_diagnostic_evidence",
        ),
    ),
)
def test_promotes_current_sre_family_with_server_owned_recent_window(
    utterance: str,
    family: OperationalPreflightFamily,
    targets: tuple[tuple[str, str], ...],
    facets: tuple[str, ...],
    expected_intent: str,
) -> None:
    operational_targets = tuple(
        SemanticTarget(
            kind=kind,
            value=value,
            source_start=utterance.index(value),
            source_end=utterance.index(value) + len(value),
        )
        for kind, value in targets
    )
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=family,
        operational_targets=operational_targets,
        operational_facets=facets,
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == expected_intent
    assert judgment.targets == operational_targets
    assert judgment.requested_facets == facets


def test_configuration_collection_derives_server_owned_recent_window() -> None:
    utterance = "구독에 배포된 GPT 리소스의 변경이 있는지 확인해보자."
    target_value = "GPT 리소스"
    target = SemanticTarget(
        kind="resource_type_filter",
        value=target_value,
        source_start=utterance.index(target_value),
        source_end=utterance.index(target_value) + len(target_value),
    )
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(target,),
        operational_facets=("configuration_changes", "gpt"),
        confidence=0.93,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.resource_configuration_changes"
    assert judgment.requested_facets == ("configuration_changes", "default_recent_window")


def test_recent_resource_state_collection_promotes_without_target() -> None:
    utterance = "최근 상태가 변경된 리소스 5개만 알려줄래?"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RECENT_RESOURCE_STATE_CHANGES,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(),
        operational_facets=("recently_changed", "resource_count", "limit_5"),
        operational_result_limit=5,
        confidence=0.97,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.resource_change_activity"
    assert judgment.targets == ()
    assert judgment.requested_facets == (
        "recently_changed",
        "resource_count",
        "default_recent_window",
        "limit_5",
    )


def test_recent_resource_changes_promote_without_state_meaning() -> None:
    utterance = "Show me recently changed resources"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RECENT_RESOURCE_CHANGES,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(),
        operational_facets=("changed_resources", "resource_count"),
        operational_result_limit=5,
        confidence=0.97,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.requested_facets == (
        "changed_resources",
        "resource_count",
        "default_recent_window",
        "limit_5",
    )


def test_recent_resource_state_collection_requires_typed_count() -> None:
    utterance = "최근 상태가 변경된 리소스 5개만 알려줄래?"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RECENT_RESOURCE_STATE_CHANGES,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(),
        operational_facets=("recently_changed", "resource_count", "limit_N"),
        confidence=0.97,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_configuration_collection_drops_server_owned_subscription_scope() -> None:
    utterance = (
        "Check whether deployed GPT resources in the subscription have configuration changes."
    )
    type_value = "deployed GPT resources"
    scope_value = "the subscription"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        operational_targets=(
            SemanticTarget(
                kind="resource_type_filter",
                value=type_value,
                source_start=utterance.index(type_value),
                source_end=utterance.index(type_value) + len(type_value),
            ),
            SemanticTarget(
                kind="resource_type_filter",
                value=scope_value,
                source_start=utterance.index(scope_value),
                source_end=utterance.index(scope_value) + len(scope_value),
            ),
        ),
        operational_facets=("configuration_changes", "potential_issues"),
        confidence=0.94,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.targets == (proposal.operational_targets[0],)
    assert judgment.requested_facets == (
        "configuration_changes",
        "potential_issues",
        "default_recent_window",
    )


def test_gateway_preflight_drops_generic_model_label_from_resource_targets() -> None:
    utterance = "SRE-APIM을 통해 GPT 5.4로 연결된 서비스에 500 Error가 발생하고 있어."
    gateway = "SRE-APIM"
    model_label = "GPT 5.4"
    targets = tuple(
        SemanticTarget(
            kind="resource",
            value=value,
            source_start=utterance.index(value),
            source_end=utterance.index(value) + len(value),
        )
        for value in (gateway, model_label)
    )
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=targets,
        operational_facets=(
            "apim",
            "configuration_changes",
            "default_recent_window",
            "gpt",
            "http_status",
            "status_500",
        ),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.gateway_diagnostic_evidence"
    assert judgment.targets == (targets[0],)
    assert judgment.requested_facets == proposal.operational_facets


def test_gateway_preflight_canonicalizes_bounded_facet_aliases() -> None:
    utterance = "SRE-APIM returns HTTP 500 for a GPT 5.4 service."
    gateway = "SRE-APIM"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=gateway,
                source_start=utterance.index(gateway),
                source_end=utterance.index(gateway) + len(gateway),
            ),
        ),
        operational_facets=(
            "api_management_issue",
            "gpt_service",
            "http_500",
            "metrics",
            "resource_configuration_changes",
            "default_recent_window",
        ),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.gateway_diagnostic_evidence"
    assert judgment.requested_facets == (
        "apim",
        "gpt",
        "status_500",
        "configuration_changes",
        "default_recent_window",
    )


def test_gateway_preflight_derives_server_owned_recent_window() -> None:
    utterance = "SRE-AppGW-01 뒤의 Client가 갑자기 느립니다."
    resource = "SRE-AppGW-01"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=resource,
                source_start=utterance.index(resource),
                source_end=utterance.index(resource) + len(resource),
            ),
        ),
        operational_facets=("application_gateway", "backend", "latency"),
        confidence=0.89,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.primary_intent == "query.gateway_diagnostic_evidence"
    assert judgment.requested_facets == (
        "application_gateway",
        "backend",
        "latency",
        "default_recent_window",
    )


def test_gateway_preflight_drops_repeated_generic_target_before_span_repair() -> None:
    utterance = "SRE-AppGW-01 has Backend latency and another Backend change."
    gateway = "SRE-AppGW-01"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=gateway,
                source_start=0,
                source_end=len(gateway),
            ),
            SemanticTarget(
                kind="resource",
                value="Backend",
                source_start=0,
                source_end=len("Backend"),
            ),
        ),
        operational_facets=("application_gateway", "backend", "latency"),
        confidence=0.9,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.targets == (proposal.operational_targets[0],)


def test_gateway_preflight_binds_unique_runtime_identifier_after_generic_target() -> None:
    utterance = "Clients using SRE-AppGW-01 report latency at the Application Gateway."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="Application Gateway",
                source_start=50,
                source_end=69,
            ),
        ),
        operational_facets=("application_gateway", "backend", "latency"),
        confidence=0.86,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert tuple((target.kind, target.value) for target in judgment.targets) == (
        ("resource", "SRE-AppGW-01"),
    )


def test_gateway_preflight_derives_recent_window_from_typed_current_error() -> None:
    utterance = "SRE-APIM returns HTTP 500 for GPT 5.4."
    gateway = "SRE-APIM"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=gateway,
                source_start=0,
                source_end=len(gateway),
            ),
            SemanticTarget(
                kind="model",
                value="GPT 5.4",
                source_start=30,
                source_end=37,
            ),
        ),
        operational_facets=("apim", "gpt", "status_500", "configuration_changes"),
        confidence=0.91,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert judgment.targets == (proposal.operational_targets[0],)
    assert judgment.requested_facets == (
        "apim",
        "gpt",
        "status_500",
        "configuration_changes",
        "default_recent_window",
    )


def test_gateway_preflight_normalizes_gateway_kind_and_generic_filters() -> None:
    utterance = "SRE-APIM reports HTTP 500 for GPT 5.4; compare APIM and GPT."
    gateway = "SRE-APIM"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_window=OperationalWindowMode.SERVER_RECENT_DEFAULT,
        operational_targets=(
            SemanticTarget(
                kind="gateway",
                value=gateway,
                source_start=utterance.index(gateway),
                source_end=utterance.index(gateway) + len(gateway),
            ),
            SemanticTarget(
                kind="resource_name_filter",
                value="APIM service",
                source_start=utterance.index("APIM", len(gateway)),
                source_end=utterance.index("APIM", len(gateway)) + len("APIM service"),
            ),
            SemanticTarget(
                kind="resource_name_filter",
                value="GPT",
                source_start=utterance.rindex("GPT"),
                source_end=utterance.rindex("GPT") + len("GPT"),
            ),
        ),
        operational_facets=("apim", "gpt", "status_500", "configuration_changes"),
        confidence=0.91,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert tuple((target.kind, target.value) for target in judgment.targets) == (
        ("resource", gateway),
    )


def test_preflight_operational_judgment_rejects_nonmatching_source_span() -> None:
    utterance = "actual-appgw latency"
    result = ConversationPreflightResult(
        proposal=ConversationPreflightProposal(
            social_act=SocialAct.NONE,
            operational_signal=OperationalSignal.EXPLICIT,
            context_dependency=ContextDependency.NONE,
            operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
            operational_targets=(
                SemanticTarget(
                    kind="resource",
                    value="invented-appgw",
                    canonical_value="Resource.name",
                    source_start=0,
                    source_end=14,
                ),
            ),
            operational_facets=("latency",),
            confidence=0.99,
        ),
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=None,
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )
    result = replace(
        result,
        proposal_digest=content_digest(result.proposal.model_dump(mode="json")),
    )

    assert (
        preflight_operational_judgment(
            result,
            utterance=utterance,
        )
        is None
    )


def test_resource_collection_preflight_rejects_exact_resource_target() -> None:
    utterance = "Show the state of aks-example-cluster."
    start = utterance.index("aks-example-cluster")
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_COLLECTION,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="aks-example-cluster",
                canonical_value="Resource.name",
                source_start=start,
                source_end=start + len("aks-example-cluster"),
            ),
        ),
        operational_facets=("resource_collection", "list"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_resource_collection_preflight_rejects_filter_inside_exact_resource() -> None:
    utterance = "aks-example-cluster 의 상태는 "
    type_value = "aks"
    state_value = "상태"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_COLLECTION,
        operational_targets=(
            SemanticTarget(
                kind="resource_type_filter",
                value=type_value,
                source_start=utterance.index(type_value),
                source_end=utterance.index(type_value) + len(type_value),
            ),
            SemanticTarget(
                kind="resource_state_filter",
                value=state_value,
                source_start=utterance.index(state_value),
                source_end=utterance.index(state_value) + len(state_value),
            ),
        ),
        operational_facets=("resource_collection", "list", "current_state"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


@pytest.mark.parametrize(
    ("utterance", "kind", "value"),
    [
        ("Show resources matching prod-db.", "resource_type_filter", "prod-db"),
        (
            "Show resources matching /subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-example/providers/Microsoft.Sql/servers/db-example.",
            "resource_name_filter",
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-example/providers/Microsoft.Sql/servers/db-example",
        ),
    ],
)
def test_resource_collection_preflight_rejects_filters_that_are_exact_identities(
    utterance: str,
    kind: str,
    value: str,
) -> None:
    start = utterance.index(value)
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_COLLECTION,
        operational_targets=(
            SemanticTarget(
                kind=kind,
                value=value,
                source_start=start,
                source_end=start + len(value),
            ),
        ),
        operational_facets=(
            "resource_collection",
            "list",
            *(("name_filter",) if kind == "resource_name_filter" else ()),
        ),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_preflight_operational_judgment_requires_current_provenance_and_confidence() -> None:
    utterance = "Document every resource in the current subscription."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.INVENTORY_DOCUMENT,
        operational_facets=(
            "resource_inventory",
            "subscription",
            "complete_content",
            "download",
        ),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert (
        preflight_operational_judgment(
            replace(result, input_digest=content_digest({"utterance": "stale"})),
            utterance=utterance,
        )
        is None
    )
    accepted_confidence = proposal.model_copy(update={"confidence": 0.75})
    assert (
        preflight_operational_judgment(
            replace(
                result,
                proposal=accepted_confidence,
                proposal_digest=content_digest(accepted_confidence.model_dump(mode="json")),
            ),
            utterance=utterance,
        )
        is not None
    )
    low_confidence = proposal.model_copy(update={"confidence": 0.74})
    assert (
        preflight_operational_judgment(
            replace(
                result,
                proposal=low_confidence,
                proposal_digest=content_digest(low_confidence.model_dump(mode="json")),
            ),
            utterance=utterance,
        )
        is None
    )


def test_subscription_scope_preflight_rejects_named_alternate_subscription() -> None:
    utterance = "Show subscription other-sub."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
        operational_facets=("subscription",),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


@pytest.mark.parametrize(
    ("utterance", "family", "facets"),
    [
        (
            "Show subscription prod.",
            OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
            ("subscription",),
        ),
        (
            "Show the Contoso subscription.",
            OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
            ("subscription",),
        ),
        (
            "Show subscription named service.",
            OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
            ("subscription",),
        ),
        (
            "Show subscription named current.",
            OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
            ("subscription",),
        ),
        (
            "prod 구독의 Service Health를 보여줘.",
            OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH,
            ("service_health",),
        ),
        (
            "고객운영 구독의 Service Health를 보여줘.",
            OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH,
            ("service_health",),
        ),
        (
            "고객운영 subscription의 Service Health를 보여줘.",
            OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH,
            ("service_health",),
        ),
        (
            "Show Service Health for subscription 고객운영.",
            OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH,
            ("service_health",),
        ),
    ],
)
def test_subscription_preflight_rejects_alphabetic_named_scope(
    utterance: str,
    family: OperationalPreflightFamily,
    facets: tuple[str, ...],
) -> None:
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=family,
        operational_facets=facets,
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


@pytest.mark.parametrize(
    "utterance",
    [
        "Show the current Azure subscription.",
        "Show the configured Azure subscription status.",
        "현재 Azure 구독 정보를 보여줘.",
    ],
)
def test_subscription_preflight_allows_generic_azure_scope(utterance: str) -> None:
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY,
        operational_facets=("subscription",),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is not None


def test_preflight_operational_judgment_rejects_false_one_hour_canonicalization() -> None:
    utterance = "Compare deployment-a configuration changes for the last day."
    resource = "deployment-a"
    period = "last day"
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=resource,
                canonical_value="Resource.name",
                source_start=utterance.index(resource),
                source_end=utterance.index(resource) + len(resource),
            ),
            SemanticTarget(
                kind="time_range",
                value=period,
                canonical_value="duration.PT1H",
                source_start=utterance.index(period),
                source_end=utterance.index(period) + len(period),
            ),
        ),
        operational_facets=("configuration_changes",),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_preflight_operational_judgment_rejects_directionless_one_hour() -> None:
    utterance = "Compare deployment-a configuration one hour from now."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="deployment-a",
                source_start=8,
                source_end=20,
            ),
            SemanticTarget(
                kind="time_range",
                value="one hour",
                canonical_value="duration.PT1H",
                source_start=35,
                source_end=43,
            ),
        ),
        operational_facets=("configuration_changes",),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_preflight_operational_judgment_repairs_one_unique_source_span() -> None:
    utterance = "Show deployment-a changes for the past hour."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="deployment-a",
                canonical_value="deployment-a",
                source_start=6,
                source_end=18,
            ),
            SemanticTarget(
                kind="time_range",
                value="the past hour",
                canonical_value="duration.PT1H",
                source_start=31,
                source_end=44,
            ),
        ),
        operational_facets=("configuration_changes", "last_hour"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    judgment = preflight_operational_judgment(result, utterance=utterance)

    assert judgment is not None
    assert all(
        utterance[target.source_start : target.source_end] == target.value
        for target in judgment.targets
    )


def test_preflight_configuration_rejects_arm_id_as_resource_name() -> None:
    resource_id = "/subscriptions/example/resourceGroups/rg/providers/Microsoft.Cognitive/x"
    utterance = f"Show {resource_id} configuration changes for the last hour."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value=resource_id,
                canonical_value=None,
                source_start=5,
                source_end=5 + len(resource_id),
            ),
            SemanticTarget(
                kind="time_range",
                value="last hour",
                canonical_value="duration.PT1H",
                source_start=utterance.index("last hour"),
                source_end=utterance.index("last hour") + len("last hour"),
            ),
        ),
        operational_facets=("configuration_changes", "last_hour"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_preflight_gateway_rejects_generic_product_targets() -> None:
    utterance = "Compare APIM backend errors with GPT."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="APIM",
                source_start=8,
                source_end=12,
            ),
            SemanticTarget(
                kind="backend",
                value="backend",
                source_start=13,
                source_end=20,
            ),
            SemanticTarget(
                kind="model",
                value="GPT",
                source_start=33,
                source_end=36,
            ),
        ),
        operational_facets=("apim", "backend", "gpt", "status_500"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


@pytest.mark.parametrize(
    "value",
    (
        "the APIM gateway",
        "selected backend",
        "our gateway",
        "my APIM service",
        "that gateway",
        "an Application Gateway",
        "현재 GPT model",
        "우리 게이트웨이",
        "그 APIM service",
        "Azure API Management service.",
        "API",
        "Backend Instance",
        "GPT 5.4",
        "5.4",
        "HTTP 500",
        "500",
    ),
)
def test_operational_target_generic_gate_normalizes_qualifiers(value: str) -> None:
    assert operational_target_is_generic(value)


def test_preflight_gateway_rejects_space_separated_identity_phrase() -> None:
    utterance = "Compare primary gateway latency during the last hour."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="primary gateway",
                source_start=8,
                source_end=23,
            ),
            SemanticTarget(
                kind="time_range",
                value="last hour",
                canonical_value="duration.PT1H",
                source_start=43,
                source_end=52,
            ),
        ),
        operational_facets=("application_gateway", "latency", "last_hour"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_preflight_gateway_requires_explicit_time_target() -> None:
    utterance = "Compare agw-example and backend latency."
    proposal = ConversationPreflightProposal(
        social_act=SocialAct.NONE,
        operational_signal=OperationalSignal.EXPLICIT,
        context_dependency=ContextDependency.NONE,
        operational_family=OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE,
        operational_targets=(
            SemanticTarget(
                kind="resource",
                value="agw-example",
                source_start=8,
                source_end=19,
            ),
        ),
        operational_facets=("application_gateway", "backend", "latency"),
        confidence=0.99,
    )
    result = ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )

    assert preflight_operational_judgment(result, utterance=utterance) is None


def test_malformed_response_retries_once_then_falls_through() -> None:
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


def test_classifier_retries_malformed_schema_once() -> None:
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
    assert result.failure_kind is None
    assert model.calls == 2
    assert model.repairs[0] == ()
    assert model.repairs[1] == (
        {
            "path": "proposal",
            "reason": "return every conditionally required field with a schema-valid value",
        },
    )


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
