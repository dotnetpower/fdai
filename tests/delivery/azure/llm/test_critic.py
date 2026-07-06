"""httpx-mocked tests for :class:`AzureOpenAICriticModel`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aiopspilot.core.quality_gate.critic import (
    CriticOutput,
    CriticSeverity,
    CriticStance,
)
from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.delivery.azure.llm.critic import (
    AzureOpenAICriticModel,
    AzureOpenAICriticModelConfig,
)
from aiopspilot.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_TEST_SYSTEM_PROMPT = "unit-test critic system prompt"


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


def _config() -> AzureOpenAICriticModelConfig:
    return AzureOpenAICriticModelConfig(
        endpoint="https://oai-test.openai.azure.com",
        deployment="t2-critic",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )


def _proposer_output() -> tuple[str, dict[str, object]]:
    return ("remediate.tag-add", {"tag_name": "owner", "tag_value": "team-a"})


# ---------------------------------------------------------------------------
# Config validation (fail-fast at construction)
# ---------------------------------------------------------------------------


def test_config_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError, match="https"):
        AzureOpenAICriticModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICriticModelConfig(
                endpoint="ftp://oai-test.openai.azure.com",
                deployment="t2-critic",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )


def test_config_rejects_empty_deployment() -> None:
    with pytest.raises(ValueError, match="deployment"):
        AzureOpenAICriticModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICriticModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )


def test_config_rejects_empty_system_prompt() -> None:
    with pytest.raises(ValueError, match="system_prompt"):
        AzureOpenAICriticModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICriticModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-critic",
                system_prompt="",
            ),
        )


def test_config_rejects_bad_temperature() -> None:
    with pytest.raises(ValueError, match="temperature"):
        AzureOpenAICriticModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICriticModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-critic",
                system_prompt=_TEST_SYSTEM_PROMPT,
                temperature=3.0,
            ),
        )


def test_config_rejects_zero_max_tokens() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        AzureOpenAICriticModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICriticModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-critic",
                system_prompt=_TEST_SYSTEM_PROMPT,
                max_tokens=0,
            ),
        )


def test_config_rejects_zero_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        AzureOpenAICriticModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICriticModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-critic",
                system_prompt=_TEST_SYSTEM_PROMPT,
                timeout_seconds=0.0,
            ),
        )


# ---------------------------------------------------------------------------
# Successful parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critique_parses_agree_with_no_objections() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_transport(
        json.dumps({"stance": "agree", "objections": [], "citations": []}),
        captured=captured,
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.critique(_candidate(), _proposer_output())
    assert isinstance(output, CriticOutput)
    assert output.stance is CriticStance.AGREE
    assert output.objections == ()
    assert output.citations == ()
    # The request body carries both the candidate and the proposer output
    # in a canonical (sorted-keys) JSON envelope.
    body = json.loads(captured[0].content.decode())
    user_content = json.loads(body["messages"][1]["content"])
    assert "candidate" in user_content
    assert "proposer_output" in user_content
    assert user_content["candidate"]["action_type"] == "remediate.tag-add"
    assert user_content["proposer_output"]["action_type"] == "remediate.tag-add"
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_critique_parses_challenge_with_objections_and_citations() -> None:
    payload = {
        "stance": "challenge",
        "objections": [
            {
                "severity": "medium",
                "cited_rule_id": "rule.b",
                "description": "parameter drift",
                "alt_action_type": "remediate.tag-update",
            },
            {
                "severity": "high",
                "cited_rule_id": "rule.a",
                "description": "blast radius overrun",
            },
        ],
        "citations": ["rule.b", "rule.a"],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.critique(_candidate(), _proposer_output())
    assert output.stance is CriticStance.CHALLENGE
    assert len(output.objections) == 2
    assert output.objections[0].severity is CriticSeverity.MEDIUM
    assert output.objections[0].cited_rule_id == "rule.b"
    assert output.objections[0].alt_action_type == "remediate.tag-update"
    assert output.objections[1].severity is CriticSeverity.HIGH
    assert output.objections[1].alt_action_type is None
    assert output.citations == ("rule.b", "rule.a")


@pytest.mark.asyncio
async def test_critique_parses_abstain_shape_with_missing_optional_fields() -> None:
    """A minimal ``abstain`` response omits ``objections`` and
    ``citations`` entirely; the parser defaults both to empty
    tuples."""

    transport = _mock_transport(json.dumps({"stance": "abstain"}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.critique(_candidate(), _proposer_output())
    assert output.stance is CriticStance.ABSTAIN
    assert output.objections == ()
    assert output.citations == ()


@pytest.mark.asyncio
async def test_critique_normalizes_empty_alt_action_to_none() -> None:
    """An empty string ``alt_action_type`` MUST NOT reach the evaluator
    as ``""`` - it is normalized to ``None`` at the boundary so downstream
    code has a single "no alternate" representation."""

    payload = {
        "stance": "challenge",
        "objections": [
            {
                "severity": "low",
                "cited_rule_id": "rule.a",
                "description": "note",
                "alt_action_type": "",
            },
        ],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        output = await adapter.critique(_candidate(), _proposer_output())
    assert output.objections[0].alt_action_type is None


# ---------------------------------------------------------------------------
# Fail-closed parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critique_rejects_non_json_content() -> None:
    transport = _mock_transport("not-json", captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="non-JSON"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_response_that_is_not_a_json_object() -> None:
    transport = _mock_transport(json.dumps([1, 2, 3]), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="MUST return a JSON object"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_missing_stance() -> None:
    transport = _mock_transport(json.dumps({"objections": []}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'stance'"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_invalid_stance_value() -> None:
    transport = _mock_transport(json.dumps({"stance": "reject"}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'stance' MUST be one of"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_non_array_objections() -> None:
    transport = _mock_transport(
        json.dumps({"stance": "agree", "objections": "not-a-list"}), captured=[]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'objections' MUST be an array"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_objection_with_bad_severity() -> None:
    payload = {
        "stance": "challenge",
        "objections": [
            {"severity": "catastrophic", "cited_rule_id": "rule.a", "description": "boom"},
        ],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="severity MUST be one of"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_objection_with_missing_cited_rule_id() -> None:
    payload = {
        "stance": "challenge",
        "objections": [{"severity": "low", "description": "no citation"}],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="cited_rule_id MUST be a string"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_objection_with_blank_description_via_post_init() -> None:
    """String type checks pass, but ``CriticObjection.__post_init__``
    refuses whitespace-only descriptions. Verifies the two layers of
    defense stack correctly (parser + dataclass)."""

    payload = {
        "stance": "challenge",
        "objections": [
            {"severity": "low", "cited_rule_id": "rule.a", "description": "   "},
        ],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(ValueError, match="description"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_rejects_non_string_citation() -> None:
    payload = {
        "stance": "agree",
        "objections": [],
        "citations": [123],
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="citations\\[0\\]"):
            await adapter.critique(_candidate(), _proposer_output())


@pytest.mark.asyncio
async def test_critique_propagates_http_status_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICriticModel(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.critique(_candidate(), _proposer_output())
