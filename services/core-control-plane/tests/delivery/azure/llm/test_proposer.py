"""AzureOpenAIProposer request minimization and fail-closed parsing tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.core.tiers.t2_reasoning import T2ProposalContext
from fdai.delivery.azure.llm import AzureOpenAIProposer, AzureOpenAIProposerConfig
from fdai.shared.contracts.models import Event, Mode, Rule


class _FakeIdentity:
    async def get_token(self, scope: str) -> object:
        assert scope.endswith("cognitiveservices.azure.com/.default")
        return SimpleNamespace(token="fake-token")


def _config() -> AzureOpenAIProposerConfig:
    return AzureOpenAIProposerConfig(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-4o",
        system_prompt="Return a bounded FDAI proposal.",
    )


def _rule(valid_rule: dict[str, Any]) -> Rule:
    raw = dict(valid_rule)
    raw.update(
        {
            "id": "compute.restart.required",
            "resource_type": "compute.vm",
            "remediates": "ops.restart-service",
        }
    )
    return Rule.model_validate(raw)


def _context(valid_rule: dict[str, Any]) -> T2ProposalContext:
    event = Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000123",  # type: ignore[arg-type]
        idempotency_key="proposer-test",
        source="example_detector",
        event_type="novel_failure",
        resource_ref="resource:private/identifier",
        payload={"resource": {"props": {"password": "must-not-leak"}}},
        detected_at="2026-07-15T00:00:00Z",  # type: ignore[arg-type]
        ingested_at="2026-07-15T00:00:01Z",  # type: ignore[arg-type]
        mode=Mode.SHADOW,
    )
    return T2ProposalContext(
        event=event,
        target_resource_ref="resource:private/identifier",
        target_resource_type="compute.vm",
        allowed_rules=(_rule(valid_rule),),
    )


def _envelope(payload: dict[str, object], *, usage: dict[str, int] | None = None) -> dict:
    envelope: dict[str, object] = {"choices": [{"message": {"content": json.dumps(payload)}}]}
    if usage is not None:
        envelope["usage"] = usage
    return envelope


def _valid_response() -> dict[str, object]:
    return {
        "abstain": False,
        "action_type": "ops.restart-service",
        "params": {"restart_reason": "health signal exceeded threshold"},
        "cited_rule_ids": ["compute.restart.required"],
        "reasoning_trace": "The cited rule authorizes a restart.",
        "target_resource_ref": "model-controlled-target-must-be-ignored",
    }


@pytest.mark.asyncio
async def test_request_is_bounded_and_target_is_caller_bound(valid_rule: dict[str, Any]) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope(_valid_response()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        proposer = AzureOpenAIProposer(
            identity=_FakeIdentity(), http_client=client, config=_config()
        )
        candidate = await proposer.propose(context=_context(valid_rule))

    assert candidate is not None
    assert candidate.target_resource_ref == "resource:private/identifier"
    assert candidate.target_resource_type == "compute.vm"
    body = captured["body"]
    assert isinstance(body, dict)
    user_prompt = body["messages"][1]["content"]
    assert "resource:private/identifier" not in user_prompt
    assert "must-not-leak" not in user_prompt
    assert "compute.restart.required" in user_prompt


@pytest.mark.asyncio
async def test_gpt5_family_uses_completion_tokens_without_temperature(
    valid_rule: dict[str, Any],
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope(_valid_response()))

    config = AzureOpenAIProposerConfig(
        endpoint="https://example.openai.azure.com",
        deployment="t2-primary",
        model_family="gpt-5.4-mini",
        system_prompt="Return a bounded FDAI proposal.",
        max_tokens=256,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        proposer = AzureOpenAIProposer(identity=_FakeIdentity(), http_client=client, config=config)
        assert await proposer.propose(context=_context(valid_rule)) is not None

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_completion_tokens"] == 256
    assert "max_tokens" not in body
    assert "temperature" not in body


@pytest.mark.asyncio
async def test_abstain_response_returns_none(valid_rule: dict[str, Any]) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=_envelope({"abstain": True}))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        proposer = AzureOpenAIProposer(
            identity=_FakeIdentity(), http_client=client, config=_config()
        )
        assert await proposer.propose(context=_context(valid_rule)) is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            {**_valid_response(), "cited_rule_ids": ["invented.rule"]},
            "outside the allowed set",
        ),
        (
            {**_valid_response(), "action_type": "ops.delete-everything"},
            "not authorized",
        ),
        (
            {**_valid_response(), "params": {"api_token": "value"}},
            "secret-like key",
        ),
        ({**_valid_response(), "params": []}, "params MUST be an object"),
        ({**_valid_response(), "cited_rule_ids": []}, "non-empty string array"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_candidate_fails_closed(
    valid_rule: dict[str, Any], response: dict[str, object], message: str
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=_envelope(response)))
    async with httpx.AsyncClient(transport=transport) as client:
        proposer = AzureOpenAIProposer(
            identity=_FakeIdentity(), http_client=client, config=_config()
        )
        with pytest.raises(RuntimeError, match=message):
            await proposer.propose(context=_context(valid_rule))


@pytest.mark.asyncio
async def test_empty_allowed_rules_abstains_without_network(valid_rule: dict[str, Any]) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    context = _context(valid_rule)
    context = T2ProposalContext(
        event=context.event,
        target_resource_ref=context.target_resource_ref,
        target_resource_type=context.target_resource_type,
        allowed_rules=(),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        proposer = AzureOpenAIProposer(
            identity=_FakeIdentity(), http_client=client, config=_config()
        )
        assert await proposer.propose(context=context) is None
    assert calls == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"endpoint": "ftp://invalid"}, "endpoint"),
        ({"deployment": ""}, "deployment"),
        ({"system_prompt": ""}, "system_prompt"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"timeout_seconds": 0.0}, "timeout_seconds"),
        ({"temperature": 3.0}, "temperature"),
    ],
)
def test_config_validation(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "endpoint": "https://example.openai.azure.com",
        "deployment": "gpt-4o",
        "system_prompt": "prompt",
    }
    values.update(kwargs)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    with pytest.raises(ValueError, match=message):
        AzureOpenAIProposer(
            identity=_FakeIdentity(),
            http_client=client,
            config=AzureOpenAIProposerConfig(**values),  # type: ignore[arg-type]
        )
