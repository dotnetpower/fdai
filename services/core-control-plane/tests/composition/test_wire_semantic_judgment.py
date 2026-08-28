"""Production semantic-judgment factory wire replays."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fdai.composition.wire_semantic_judgment import build_azure_semantic_judgment_factory
from fdai.core.prompts import DefaultPromptComposer, FileSystemPromptRegistry
from fdai.rule_catalog.schema.llm_resolver import NarratorCandidate, ResolvedModels
from fdai.shared.providers.workload_identity import IdentityToken

NOW = datetime(2026, 8, 24, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken("test-token", NOW + timedelta(minutes=5), audience)


def _proposal(
    *,
    conversation_act: str,
    primary_intent: str,
    action_subject: str = "none",
) -> dict[str, object]:
    action_draft = conversation_act == "action_draft_request"
    return {
        "primary_intent": primary_intent,
        "secondary_intents": [],
        "targets": [],
        "requested_facets": [],
        "confidence": 0.97,
        "ambiguous": False,
        "alternatives": [],
        "unresolved_terms": [],
        "clarification": None,
        "discourse_mode": "direct",
        "action_posture": "draft_only" if action_draft else "advise_only",
        "action_subject": action_subject,
        "authority": "candidate_only",
        "execution_authority": False,
    }


_CASES = (
    (
        "Hello",
        _proposal(
            conversation_act="direct_social",
            primary_intent="greeting",
        ),
    ),
    (
        "안뇽",
        _proposal(
            conversation_act="direct_social",
            primary_intent="greeting",
        ),
    ),
    (
        "What is the weather in Seoul now?",
        _proposal(
            conversation_act="information_request",
            primary_intent="external.current_information",
        ),
    ),
    (
        "지금 서울 날씨가 어때?",
        _proposal(
            conversation_act="information_request",
            primary_intent="external.current_information",
        ),
    ),
    (
        "Search the public web for the current Azure service status.",
        _proposal(
            conversation_act="information_request",
            primary_intent="external.public_information",
        ),
    ),
    (
        "공개 웹에서 현재 Azure 서비스 상태를 찾아줘.",
        _proposal(
            conversation_act="information_request",
            primary_intent="external.public_information",
        ),
    ),
    (
        "Hi, show the current resource status.",
        _proposal(
            conversation_act="information_request",
            primary_intent="resource.status",
        ),
    ),
    (
        "The runbook says 'draft a rollback'; what does that sentence mean?",
        _proposal(
            conversation_act="information_request",
            primary_intent="explain_text",
        ),
    ),
    (
        "If someone drafted a rollback, which approval would it need?",
        _proposal(
            conversation_act="information_request",
            primary_intent="approval.requirements",
        ),
    ),
    (
        "Draft a review-only rollback proposal.",
        _proposal(
            conversation_act="action_draft_request",
            primary_intent="action_request",
            action_subject="Change",
        ),
    ),
    (
        "검토 전용 롤백 제안을 작성해 줘.",
        _proposal(
            conversation_act="action_draft_request",
            primary_intent="action_request",
            action_subject="Change",
        ),
    ),
    (
        "Search the web for guidance, but do not send private resource identifiers.",
        _proposal(
            conversation_act="information_request",
            primary_intent="external.public_information",
        ),
    ),
)


@pytest.mark.parametrize(("utterance", "proposal"), _CASES)
async def test_production_factory_replays_typed_routes_without_local_text_routing(
    utterance: str,
    proposal: dict[str, object],
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        request_body = json.loads(request.content)
        untrusted = json.loads(request_body["messages"][1]["content"])["untrusted_input"]
        response_proposal = dict(proposal)
        if proposal["primary_intent"] == "greeting":
            response_proposal["direct_response"] = {
                "locale": untrusted["locale"],
                "answer": (
                    "반갑습니다. 무엇을 함께 살펴볼까요?"
                    if untrusted["locale"] == "ko"
                    else "Good to meet you. What should we inspect?"
                ),
                "profile_digest": untrusted["direct_response_profile_digest"],
                "execution_authority": False,
            }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(response_proposal)}}]},
        )

    resolved = ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(),
        narrator_candidates=(
            NarratorCandidate(
                endpoint="https://models.example.com",
                deployment="semantic-t1",
            ),
        ),
        reasoner_primary_candidates=(
            NarratorCandidate(
                endpoint="https://models.example.com",
                deployment="semantic-t2",
            ),
        ),
    )
    factory = build_azure_semantic_judgment_factory(
        resolved=resolved,
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        endpoint=None,
        endpoint_resolver=None,
        system_prompt="Return one typed semantic judgment object.",
    )
    assert factory is not None
    boundary = factory(asyncio.get_running_loop())

    result = await asyncio.to_thread(
        boundary.judge,
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "information_source", "name": "external.public_web", "available": True},
            {
                "kind": "information_source",
                "name": "external.current_weather",
                "available": False,
            },
        ),
        locale="ko" if utterance == "안뇽" else "en",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == proposal["primary_intent"]
    assert result.proposal.action_posture == proposal["action_posture"]
    assert len(requests) == 1
    for request in requests:
        body = json.loads(request.content)
        untrusted = json.loads(body["messages"][1]["content"])["untrusted_input"]
        assert untrusted["utterance"] == utterance
        assert untrusted["capabilities"][0]["kind"] == "information_source"


async def test_production_factory_uses_compact_preflight_before_full_judgment() -> None:
    requests: list[httpx.Request] = []
    repo_root = Path(__file__).resolve().parents[4]
    preflight_prompt = (
        FileSystemPromptRegistry(repo_root / "rule-catalog").get_base("conversation.preflight").body
    )
    narrator_prompt = (
        await DefaultPromptComposer(
            registry=FileSystemPromptRegistry(repo_root / "rule-catalog")
        ).compose(capability_id="conversation.social-narrator.greeting")
    ).system_text

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        untrusted = json.loads(body["messages"][1]["content"])["untrusted_input"]
        if "social response for FDAI Console" in body["messages"][0]["content"]:
            proposal = {
                "locale": untrusted["locale"],
                "answer": "반가워요. 무엇을 함께 살펴볼까요?",
                "profile_digest": untrusted["direct_response_profile_digest"],
                "execution_authority": False,
            }
        else:
            proposal = {
                "social_act": "greeting",
                "operational_signal": "none",
                "context_dependency": "none",
                "confidence": 0.98,
                "execution_authority": False,
            }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(proposal)}}]},
        )

    resolved = ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(),
        narrator_candidates=(
            NarratorCandidate(
                endpoint="https://models.example.com",
                deployment="semantic-t1",
            ),
        ),
        reasoner_primary_candidates=(),
    )
    factory = build_azure_semantic_judgment_factory(
        resolved=resolved,
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        endpoint=None,
        endpoint_resolver=None,
        system_prompt="Full operational semantic judgment prompt.",
        preflight_system_prompt=preflight_prompt,
        social_narrator_system_prompts={"greeting": narrator_prompt},
    )
    assert factory is not None
    boundary = factory(asyncio.get_running_loop())

    result = await asyncio.to_thread(
        boundary.preflight,
        utterance="안녕",
        context=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.proposal is not None
    narrated = await asyncio.to_thread(
        boundary.narrate_social,
        utterance="안녕",
        locale="ko",
        social_act=result.proposal.social_act,
        continued=False,
        direct_response_profile={"identity": "Bragi"},
    )
    assert narrated.draft is not None
    assert narrated.draft.answer == "반가워요. 무엇을 함께 살펴볼까요?"
    assert len(requests) == 2
    classifier_body = json.loads(requests[0].content)
    narrator_body = json.loads(requests[1].content)
    system_message = classifier_body["messages"][0]["content"]
    user_message = classifier_body["messages"][1]["content"]
    assert len(system_message) < 5_400
    assert len(user_message) < 1_000
    assert "SemanticJudgmentProposal" not in system_message
    assert classifier_body["temperature"] == 0.0
    assert narrator_body["temperature"] == 0.3
    narrator_input = json.loads(narrator_body["messages"][1]["content"])["untrusted_input"]
    assert "context" not in narrator_input
    assert "capabilities" not in narrator_input
