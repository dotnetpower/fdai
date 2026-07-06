"""httpx-mocked tests for :class:`AzureOpenAIJudgeModel`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aiopspilot.core.quality_gate.critic import (
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
)
from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.core.quality_gate.judge import (
    JudgeDecision,
    JudgeOutput,
)
from aiopspilot.delivery.azure.llm.judge import (
    AzureOpenAIJudgeModel,
    AzureOpenAIJudgeModelConfig,
)
from aiopspilot.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_TEST_SYSTEM_PROMPT = "unit-test judge system prompt"


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake in-memory token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _mock_transport(content: str, *, captured: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    return httpx.MockTransport(handler)


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("object-storage.owner-tag.required",),
    )


def _config() -> AzureOpenAIJudgeModelConfig:
    return AzureOpenAIJudgeModelConfig(
        endpoint="https://oai-test.openai.azure.com",
        deployment="t1-judge",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )


def _proposer_output() -> tuple[str, dict[str, object]]:
    return ("remediate.tag-add", {"tag_name": "owner", "tag_value": "team-a"})


def _critic_output(*, stance: CriticStance = CriticStance.AGREE) -> CriticOutput:
    if stance is CriticStance.CHALLENGE:
        return CriticOutput(
            stance=stance,
            objections=(
                CriticObjection(
                    severity=CriticSeverity.MEDIUM,
                    cited_rule_id="rule.a",
                    description="parameter drift",
                ),
            ),
        )
    return CriticOutput(stance=stance)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError, match="https"):
        AzureOpenAIJudgeModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIJudgeModelConfig(
                endpoint="ftp://oai-test.openai.azure.com",
                deployment="t1-judge",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )


def test_config_rejects_empty_deployment() -> None:
    with pytest.raises(ValueError, match="deployment"):
        AzureOpenAIJudgeModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIJudgeModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )


def test_config_rejects_empty_system_prompt() -> None:
    with pytest.raises(ValueError, match="system_prompt"):
        AzureOpenAIJudgeModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIJudgeModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-judge",
                system_prompt="",
            ),
        )


def test_config_rejects_bad_temperature() -> None:
    with pytest.raises(ValueError, match="temperature"):
        AzureOpenAIJudgeModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIJudgeModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-judge",
                system_prompt=_TEST_SYSTEM_PROMPT,
                temperature=-0.1,
            ),
        )


def test_config_rejects_zero_max_tokens() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        AzureOpenAIJudgeModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIJudgeModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-judge",
                system_prompt=_TEST_SYSTEM_PROMPT,
                max_tokens=0,
            ),
        )


def test_config_rejects_zero_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        AzureOpenAIJudgeModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIJudgeModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-judge",
                system_prompt=_TEST_SYSTEM_PROMPT,
                timeout_seconds=0.0,
            ),
        )


# ---------------------------------------------------------------------------
# Successful parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_parses_accept_decision() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_transport(
        json.dumps(
            {
                "decision": "accept",
                "justification": "candidate matches the cited rule",
                "citations": ["rule.a"],
            }
        ),
        captured=captured,
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.judge(_candidate(), _proposer_output(), _critic_output())
    assert isinstance(output, JudgeOutput)
    assert output.decision is JudgeDecision.ACCEPT
    assert output.retry_directive is None
    assert output.citations == ("rule.a",)
    # Payload includes candidate + proposer_output + critic_output envelope.
    body = json.loads(captured[0].content.decode())
    user_content = json.loads(body["messages"][1]["content"])
    assert set(user_content.keys()) == {"candidate", "proposer_output", "critic_output"}
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_judge_parses_revise_and_retry_with_directive() -> None:
    payload = {
        "decision": "revise_and_retry",
        "justification": "params look off",
        "retry_directive": "swap tag_value to team-b",
        "citations": ["rule.b"],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.judge(
            _candidate(), _proposer_output(), _critic_output(stance=CriticStance.CHALLENGE)
        )
    assert output.decision is JudgeDecision.REVISE_AND_RETRY
    assert output.retry_directive == "swap tag_value to team-b"


@pytest.mark.asyncio
async def test_judge_parses_escalate_hil_with_minimal_shape() -> None:
    transport = _mock_transport(
        json.dumps({"decision": "escalate_hil", "justification": "risk too high"}),
        captured=[],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.judge(_candidate(), _proposer_output(), _critic_output())
    assert output.decision is JudgeDecision.ESCALATE_HIL
    assert output.retry_directive is None
    assert output.citations == ()


@pytest.mark.asyncio
async def test_judge_normalizes_empty_retry_directive_to_none() -> None:
    payload = {
        "decision": "accept",
        "justification": "ok",
        "retry_directive": "",
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.judge(_candidate(), _proposer_output(), _critic_output())
    assert output.retry_directive is None


# ---------------------------------------------------------------------------
# Fail-closed parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_rejects_non_json_content() -> None:
    transport = _mock_transport("not-json", captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="non-JSON"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_non_object_response() -> None:
    transport = _mock_transport(json.dumps([1, 2, 3]), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="MUST return a JSON object"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_missing_decision() -> None:
    transport = _mock_transport(json.dumps({"justification": "hi"}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'decision'"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_invalid_decision_value() -> None:
    transport = _mock_transport(
        json.dumps({"decision": "maybe", "justification": "hi"}), captured=[]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'decision' MUST be one of"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_missing_justification() -> None:
    transport = _mock_transport(json.dumps({"decision": "accept"}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'justification' MUST be a string"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_blank_justification_via_post_init() -> None:
    """String type check passes, but ``JudgeOutput.__post_init__``
    refuses whitespace-only justification. Verifies the two-layer
    defense stacks correctly."""

    transport = _mock_transport(
        json.dumps({"decision": "accept", "justification": "   "}), captured=[]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(ValueError, match="justification"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_non_array_citations() -> None:
    transport = _mock_transport(
        json.dumps({"decision": "accept", "justification": "ok", "citations": "not-a-list"}),
        captured=[],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'citations' MUST be an array"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_bad_retry_directive_type() -> None:
    transport = _mock_transport(
        json.dumps({"decision": "revise_and_retry", "justification": "hi", "retry_directive": 42}),
        captured=[],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'retry_directive'"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_rejects_non_string_citation() -> None:
    transport = _mock_transport(
        json.dumps({"decision": "accept", "justification": "ok", "citations": [42]}),
        captured=[],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="citations\\[0\\]"):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())


@pytest.mark.asyncio
async def test_judge_propagates_http_status_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIJudgeModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.judge(_candidate(), _proposer_output(), _critic_output())
