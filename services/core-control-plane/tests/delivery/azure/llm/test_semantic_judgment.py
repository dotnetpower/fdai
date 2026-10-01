"""Strict structured-output contracts for semantic judgment."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.core.conversation.conversation_preflight import ConversationPreflightProposal
from fdai.core.prompts import PromptAssembler, PromptReplayManifest, estimate_chat_request_tokens
from fdai.delivery.azure.llm.model_trace import prepare_model_messages
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_judgment import (
    AzureOpenAISemanticJudgmentModel,
    AzureOpenAISemanticJudgmentModelConfig,
    _semantic_judgment_proposal_schema,
    _strict_response_format,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def _assert_strict_objects(value: object) -> None:
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            assert value.get("additionalProperties") is False
            assert value.get("required") == list(properties)
        assert not {
            "default",
            "title",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
        }.intersection(value)
        for nested in value.values():
            _assert_strict_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_strict_objects(nested)


def test_semantic_judgment_uses_strict_structured_output() -> None:
    response_format = _strict_response_format(
        SemanticJudgmentProposal.model_json_schema(),
        name="semantic-judgment",
    )

    assert response_format["type"] == "json_schema"
    envelope = response_format["json_schema"]
    assert isinstance(envelope, Mapping)
    assert envelope["name"] == "semantic-judgment"
    assert envelope["strict"] is True
    _assert_strict_objects(envelope["schema"])
    schema = envelope["schema"]
    assert isinstance(schema, Mapping)
    properties = schema["properties"]
    assert isinstance(properties, Mapping)
    alternatives = properties["alternatives"]
    unresolved_terms = properties["unresolved_terms"]
    clarification_property = properties["clarification"]
    assert isinstance(alternatives, Mapping)
    assert isinstance(unresolved_terms, Mapping)
    assert isinstance(clarification_property, Mapping)
    assert str(alternatives["description"]).startswith("At most 8")
    assert str(unresolved_terms["description"]).startswith("At most 8")
    clarification_options = clarification_property["anyOf"]
    assert isinstance(clarification_options, list)
    clarification = clarification_options[0]
    assert isinstance(clarification, Mapping)
    assert "when ambiguous is true" in clarification["description"]


def test_forbidden_actions_schema_requires_explicit_shadow_opt_in() -> None:
    active_schema = _semantic_judgment_proposal_schema(intent_hardening_enabled=False)
    shadow_schema = _semantic_judgment_proposal_schema(intent_hardening_enabled=True)

    assert "forbidden_actions" not in active_schema["properties"]
    assert "forbidden_actions" in shadow_schema["properties"]
    assert active_schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert shadow_schema["properties"]["schema_version"]["const"] == "1.1.0"
    active_strict = _strict_response_format(active_schema, name="semantic-judgment")
    shadow_strict = _strict_response_format(shadow_schema, name="semantic-judgment-shadow")
    assert "forbidden_actions" not in active_strict["json_schema"]["schema"]["required"]
    assert "forbidden_actions" in shadow_strict["json_schema"]["schema"]["required"]


def test_constraint_slots_schema_requires_explicit_shadow_opt_in() -> None:
    active_schema = _semantic_judgment_proposal_schema(intent_hardening_enabled=False)
    slot_schema = _semantic_judgment_proposal_schema(
        intent_hardening_enabled=False,
        constraint_slots_enabled=True,
    )

    assert "constraint_slots" not in active_schema["properties"]
    assert "constraint_slots" in slot_schema["properties"]
    assert active_schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert slot_schema["properties"]["schema_version"]["const"] == "1.3.0"
    active_strict = _strict_response_format(active_schema, name="semantic-judgment")
    slot_strict = _strict_response_format(slot_schema, name="semantic-judgment-slots")
    assert "constraint_slots" not in active_strict["json_schema"]["schema"]["required"]
    assert "constraint_slots" in slot_strict["json_schema"]["schema"]["required"]


def test_config_rejects_output_above_profile_reserve() -> None:
    prompt = "Judge."
    manifest = PromptReplayManifest(
        system_text_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        layer_manifest=(),
        token_estimate=2,
        profile_id="active.test",
        profile_version=1,
        profile_digest="sha256:" + ("a" * 64),
        system_token_budget=128,
        request_token_budget=16_384,
        reserved_output_tokens=1,
    )
    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )

    with pytest.raises(ValueError, match="output reserve"):
        AzureOpenAISemanticJudgmentModelConfig(
            candidates=(candidate,),
            system_prompt=prompt,
            system_prompt_manifest=manifest,
            max_tokens=2,
        )


def test_conversation_preflight_uses_the_same_strict_contract() -> None:
    response_format = _strict_response_format(
        ConversationPreflightProposal.model_json_schema(),
        name="conversation-preflight",
    )

    envelope = response_format["json_schema"]
    assert isinstance(envelope, Mapping)
    _assert_strict_objects(envelope["schema"])


@pytest.mark.asyncio
async def test_profile_request_budget_blocks_judgment_provider_call() -> None:
    prompt = "Judge."
    manifest = PromptReplayManifest(
        system_text_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        layer_manifest=(),
        token_estimate=2,
        profile_id="active.test",
        profile_version=1,
        profile_digest="sha256:" + ("a" * 64),
        system_token_budget=128,
        request_token_budget=513,
        reserved_output_tokens=512,
    )
    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )

    class _Identity:
        async def get_token(self, audience: str) -> IdentityToken:
            raise AssertionError(f"unexpected identity request for {audience}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: pytest.fail("unexpected provider call"))
    ) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=(candidate,),
                system_prompt=prompt,
                system_prompt_manifest=manifest,
                max_tokens=512,
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        result = await model._complete_attempts(
            '{"utterance":"현재 상태를 알려줘"}',
            input_digest="sha256:" + ("a" * 64),
            proposal_schema=SemanticJudgmentProposal.model_json_schema(),
            system_prompt=prompt,
            prompt_manifest=manifest,
            call_kind="semantic-judgment",
            max_tokens=512,
            temperature=0.0,
            timeout_seconds=10,
            allow_candidate_failover=False,
        )

    assert result is None


@pytest.mark.asyncio
async def test_request_budget_uses_final_sanitized_messages() -> None:
    prompt = "Judge."
    user_content = json.dumps({"value": " ".join(["a@b.co"] * 100)})
    raw_messages = (
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    )
    prepared_messages = prepare_model_messages(raw_messages).messages
    response_format = _strict_response_format(
        SemanticJudgmentProposal.model_json_schema(),
        name="semantic-judgment",
    )
    raw_estimate = estimate_chat_request_tokens(
        messages=raw_messages,
        response_format=response_format,
        reserved_output_tokens=512,
    )
    prepared_estimate = estimate_chat_request_tokens(
        messages=prepared_messages,
        response_format=response_format,
        reserved_output_tokens=512,
    )
    assert prepared_estimate > raw_estimate
    manifest = PromptReplayManifest(
        system_text_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        layer_manifest=(),
        token_estimate=len(prompt),
        profile_id="active.test",
        profile_version=1,
        profile_digest="sha256:" + ("a" * 64),
        system_token_budget=128,
        request_token_budget=raw_estimate,
        reserved_output_tokens=512,
    )
    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )

    class NoIdentity:
        async def get_token(self, audience: str) -> IdentityToken:
            raise AssertionError(f"unexpected identity request for {audience}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: pytest.fail("unexpected provider call"))
    ) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=NoIdentity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=(candidate,),
                system_prompt=prompt,
                system_prompt_manifest=manifest,
                max_tokens=512,
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        result = await model._complete_attempts(
            user_content,
            input_digest="sha256:" + ("a" * 64),
            proposal_schema=SemanticJudgmentProposal.model_json_schema(),
            system_prompt=prompt,
            prompt_manifest=manifest,
            call_kind="semantic-judgment",
            max_tokens=512,
            temperature=0.0,
            timeout_seconds=10,
            allow_candidate_failover=False,
        )

    assert result is None


def test_strict_structured_output_normalizes_schema_name_without_regex() -> None:
    response_format = _strict_response_format(
        SemanticJudgmentProposal.model_json_schema(),
        name="semantic judgment/v1",
    )

    envelope = response_format["json_schema"]
    assert isinstance(envelope, Mapping)
    assert envelope["name"] == "semantic_judgment_v1"


@pytest.mark.asyncio
async def test_conversation_preflight_never_fails_over_to_a_second_candidate() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request)

    class _Identity:
        async def get_token(self, audience: str) -> IdentityToken:
            return IdentityToken(
                "test-token",
                datetime.now(UTC) + timedelta(minutes=5),
                audience,
            )

    candidates = tuple(
        ModelRequestTarget(
            endpoint=f"https://candidate-{index}.example",
            deployment=f"candidate-{index}",
            api_version="2024-06-01",
        )
        for index in (1, 2)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=candidates,
                system_prompt="Judge.",
                preflight_system_prompt="Classify.",
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        result = await asyncio.to_thread(
            model.preflight,
            utterance="Compare blue-green and canary.",
            context=(),
            locale="en",
            direct_response_profile={"identity": "Bragi"},
            direct_response_profile_digest="sha256:" + ("a" * 64),
            schema_repair=(),
        )

    assert result is None
    assert len(requests) == 1
    assert "candidate-1" in str(requests[0].url)


@pytest.mark.asyncio
async def test_gpt5_conversation_preflight_uses_minimal_reasoning_effort() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(503, request=request)

    class _Identity:
        async def get_token(self, audience: str) -> IdentityToken:
            return IdentityToken(
                "test-token",
                datetime.now(UTC) + timedelta(minutes=5),
                audience,
            )

    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="gpt-5.6-sol",
        api_version="2024-12-01-preview",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=(candidate,),
                system_prompt="Judge.",
                preflight_system_prompt="Classify.",
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        result = await asyncio.to_thread(
            model.preflight,
            utterance="Compare blue-green and canary.",
            context=(),
            locale="en",
            direct_response_profile={"identity": "Bragi"},
            direct_response_profile_digest="sha256:" + ("a" * 64),
            schema_repair=(),
        )

    assert result is None
    assert requests[0]["reasoning_effort"] == "minimal"
    assert requests[0]["max_completion_tokens"] == 768


@pytest.mark.asyncio
async def test_conversation_preflight_cancellation_stops_the_provider_request() -> None:
    started = asyncio.Event()
    provider_cancelled = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            provider_cancelled.set()
            raise
        return httpx.Response(200, request=request)

    class _Identity:
        async def get_token(self, audience: str) -> IdentityToken:
            return IdentityToken(
                "test-token",
                datetime.now(UTC) + timedelta(minutes=5),
                audience,
            )

    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=(candidate,),
                system_prompt="Judge.",
                preflight_system_prompt="Classify.",
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        pending = asyncio.create_task(
            asyncio.to_thread(
                model.preflight,
                utterance="Compare blue-green and canary.",
                context=(),
                locale="en",
                direct_response_profile={"identity": "Bragi"},
                direct_response_profile_digest="sha256:" + ("a" * 64),
                schema_repair=(),
                cancelled=cancelled,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        cancelled.set()
        assert await asyncio.wait_for(pending, timeout=1) is None
        await asyncio.wait_for(provider_cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_parent_cancellation_stops_the_provider_request() -> None:
    started = asyncio.Event()
    provider_cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            provider_cancelled.set()
            raise
        return httpx.Response(200, request=request)

    class _Identity:
        async def get_token(self, audience: str) -> IdentityToken:
            return IdentityToken(
                "test-token",
                datetime.now(UTC) + timedelta(minutes=5),
                audience,
            )

    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=(candidate,),
                system_prompt="Judge.",
                preflight_system_prompt="Classify.",
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        pending = asyncio.create_task(
            model._complete(
                "{}",
                input_digest="sha256:" + ("a" * 64),
                proposal_schema=ConversationPreflightProposal.model_json_schema(),
                system_prompt="Classify.",
                call_kind="conversation-preflight",
                max_tokens=512,
                temperature=0.0,
                timeout_seconds=10,
                allow_candidate_failover=False,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(provider_cancelled.wait(), timeout=1)


def _dynamic_assembler() -> PromptAssembler:
    from fdai.core.prompts import (
        PromptArtifactRef,
        PromptLayer,
        PromptProfile,
        PromptProfileMode,
        PromptSelection,
    )
    from fdai.core.prompts.types import PromptArtifact, PromptMode

    def artifact(artifact_id: str, layer: PromptLayer = PromptLayer.PACK) -> PromptArtifact:
        return PromptArtifact(
            id=artifact_id,
            version=1,
            layer=layer,
            body=f"{artifact_id} guidance.",
            applies_to=("semantic.judgment",),
            token_budget=None,
            default_mode=PromptMode.SHADOW,
            provenance_source="test",
        )

    profile = PromptProfile(
        id="shadow.test-dynamic",
        version=1,
        capability_id="semantic.judgment",
        mode=PromptProfileMode.SHADOW,
        root=PromptArtifactRef("core", 1, PromptLayer.BASE),
        packs=(
            PromptArtifactRef(
                "inventory",
                1,
                PromptLayer.PACK,
                when_any=("topic:resource_inventory",),
                covers=("intent:query.contextual_resources",),
            ),
            PromptArtifactRef("ontology", 1, PromptLayer.PACK, when_any=("topic:ontology_schema",)),
        ),
        system_token_budget=4096,
        request_token_budget=65_536,
        reserved_output_tokens=2048,
        promotion_evidence=(),
        provenance_source="test",
    )
    return PromptAssembler(
        PromptSelection(
            root=artifact("core", PromptLayer.BASE),
            packs=(artifact("inventory"), artifact("ontology")),
            profile=profile,
        )
    )


def test_assembler_must_match_the_complete_configured_prompt() -> None:
    assembler = _dynamic_assembler()
    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )

    with pytest.raises(ValueError, match="assembler MUST match"):
        AzureOpenAISemanticJudgmentModelConfig(
            candidates=(candidate,),
            system_prompt="Different.",
            system_prompt_assembler=assembler,
        )


@pytest.mark.asyncio
async def test_judgment_transmits_the_route_selected_prompt_and_manifest() -> None:
    assembler = _dynamic_assembler()
    systems: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        systems.append(body["messages"][0]["content"])
        return httpx.Response(503, request=request)

    class _Identity:
        async def get_token(self, audience: str) -> IdentityToken:
            return IdentityToken(
                "test-token",
                datetime.now(UTC) + timedelta(minutes=5),
                audience,
            )

    candidate = ModelRequestTarget(
        endpoint="https://candidate.example",
        deployment="candidate",
        api_version="2024-06-01",
    )
    complete = assembler.complete
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAISemanticJudgmentModel(
            identity=_Identity(),
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=(candidate,),
                system_prompt=complete.system_text,
                system_prompt_manifest=complete.replay_manifest(),
                system_prompt_assembler=assembler,
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        arguments = {
            "utterance": "List the virtual machines",
            "context": (),
            "capabilities": (),
            "locale": "en",
            "direct_response_profile": {"identity": "Bragi"},
            "direct_response_profile_digest": "sha256:" + ("a" * 64),
            "profile_id": "pantheon-conversation",
            "profile_version": "1.0.0",
            "schema_repair": (),
        }
        await asyncio.to_thread(
            model.judge, **arguments, prompt_assembly_keys=("topic:resource_inventory",)
        )
        await asyncio.to_thread(model.judge, **arguments)

    assert model.supports_prompt_assembly
    assert systems[0] == "core guidance.\n\ninventory guidance."
    assert systems[-1] == complete.system_text


def test_preflight_requests_topics_only_from_a_topic_defining_prompt() -> None:
    from fdai.core.prompts import LayerRef, PromptLayer
    from fdai.delivery.azure.llm.semantic_judgment import _preflight_proposal_schema

    def manifest(layer_id: str) -> PromptReplayManifest:
        return PromptReplayManifest(
            system_text_sha256="a" * 64,
            layer_manifest=(
                LayerRef(id=layer_id, version=1, layer=PromptLayer.PACK, token_estimate=1),
            ),
            token_estimate=1,
        )

    assert "request_topics" not in _preflight_proposal_schema(None)["properties"]
    assert (
        "request_topics"
        not in _preflight_proposal_schema(manifest("conversation-preflight-schema-scope"))[
            "properties"
        ]
    )
    topics = _preflight_proposal_schema(manifest("conversation-preflight-request-topics"))
    assert topics["properties"]["request_topics"]["maxItems"] == 3
