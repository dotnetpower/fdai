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
    evidence_need: str,
    primary_intent: str,
    capability_ref: str | None = None,
    external_query: str | None = None,
    action_subject: str = "none",
) -> dict[str, object]:
    action_draft = conversation_act == "action_draft_request"
    return {
        "conversation_act": conversation_act,
        "evidence_need": evidence_need,
        "capability_ref": capability_ref,
        "external_query": external_query,
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
            evidence_need="none",
            primary_intent="greeting",
        ),
    ),
    (
        "안뇽",
        _proposal(
            conversation_act="direct_social",
            evidence_need="none",
            primary_intent="greeting",
        ),
    ),
    (
        "What is the weather in Seoul now?",
        _proposal(
            conversation_act="information_request",
            evidence_need="external",
            primary_intent="external.current_information",
            capability_ref="external.current_weather",
            external_query="current weather in Seoul",
        ),
    ),
    (
        "지금 서울 날씨가 어때?",
        _proposal(
            conversation_act="information_request",
            evidence_need="external",
            primary_intent="external.current_information",
            capability_ref="external.current_weather",
            external_query="current weather in Seoul",
        ),
    ),
    (
        "Search the public web for the current Azure service status.",
        _proposal(
            conversation_act="information_request",
            evidence_need="external",
            primary_intent="external.public_information",
            capability_ref="external.public_web",
            external_query="current Azure service status",
        ),
    ),
    (
        "공개 웹에서 현재 Azure 서비스 상태를 찾아줘.",
        _proposal(
            conversation_act="information_request",
            evidence_need="external",
            primary_intent="external.public_information",
            capability_ref="external.public_web",
            external_query="current Azure service status",
        ),
    ),
    (
        "Hi, show the current resource status.",
        _proposal(
            conversation_act="information_request",
            evidence_need="operational",
            primary_intent="resource.status",
        ),
    ),
    (
        "The runbook says 'draft a rollback'; what does that sentence mean?",
        _proposal(
            conversation_act="information_request",
            evidence_need="screen",
            primary_intent="explain_text",
        ),
    ),
    (
        "If someone drafted a rollback, which approval would it need?",
        _proposal(
            conversation_act="information_request",
            evidence_need="operational",
            primary_intent="approval.requirements",
        ),
    ),
    (
        "Draft a review-only rollback proposal.",
        _proposal(
            conversation_act="action_draft_request",
            evidence_need="operational",
            primary_intent="action_request",
            action_subject="Change",
        ),
    ),
    (
        "검토 전용 롤백 제안을 작성해 줘.",
        _proposal(
            conversation_act="action_draft_request",
            evidence_need="operational",
            primary_intent="action_request",
            action_subject="Change",
        ),
    ),
    (
        "Search the web for guidance, but do not send private resource identifiers.",
        _proposal(
            conversation_act="information_request",
            evidence_need="external",
            primary_intent="external.public_information",
            capability_ref="external.public_web",
            external_query="public cloud operations guidance",
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
    assert result.proposal.conversation_act.value == proposal["conversation_act"]
    assert result.proposal.evidence_need.value == proposal["evidence_need"]
    expected_calls = 2 if proposal["conversation_act"] == "action_draft_request" else 1
    assert len(requests) == expected_calls
    for request in requests:
        body = json.loads(request.content)
        untrusted = json.loads(body["messages"][1]["content"])["untrusted_input"]
        assert untrusted["utterance"] == utterance
        assert untrusted["capabilities"][0]["kind"] == "information_source"
    if proposal["evidence_need"] == "external":
        assert result.proposal.capability_ref == proposal["capability_ref"]
        assert result.proposal.external_query == proposal["external_query"]
