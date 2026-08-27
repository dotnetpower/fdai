"""Production semantic-judgment factory wire replays."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.composition.wire_semantic_judgment import build_azure_semantic_judgment_factory
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
