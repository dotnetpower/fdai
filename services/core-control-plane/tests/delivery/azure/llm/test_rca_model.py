"""AzureOpenAIRcaModel - httpx-mocked adapter logic (no live LLM).

Exercises the deterministic parts: URL + JSON body shape, the grounding
constraint in the user prompt, content extraction, HTTP-error and
malformed-envelope raising, and the LlmRcaReasoner integration that
parses the adapter's output.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fdai.core.rca import Citation, CitationKind, LlmRcaReasoner, RcaTier
from fdai.delivery.azure.llm import AzureOpenAIRcaModel, AzureOpenAIRcaModelConfig

_CANDIDATES = (
    Citation(kind=CitationKind.RULE, ref="object-storage.owner-tag.required"),
    Citation(kind=CitationKind.EVENT, ref="e-1"),
)


class _FakeIdentity:
    async def get_token(self, scope: str) -> object:
        assert scope.endswith("cognitiveservices.azure.com/.default")
        return SimpleNamespace(token="fake-token")


def _config() -> AzureOpenAIRcaModelConfig:
    return AzureOpenAIRcaModelConfig(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-4o-mini",
        system_prompt="You are an FDAI root-cause reasoner.",
    )


def _envelope(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


def _grounded_answer() -> str:
    return json.dumps(
        {
            "cause": "runaway writer",
            "confidence": 0.85,
            "citations": ["object-storage.owner-tag.required"],
        }
    )


@pytest.mark.asyncio
async def test_propose_cause_builds_request_and_returns_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope(_grounded_answer()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIRcaModel(identity=_FakeIdentity(), http_client=client, config=_config())
        content = await model.propose_cause(
            incident_summary="disk near full", candidate_citations=_CANDIDATES
        )

    assert '"cause"' in content
    url = captured["url"]
    assert isinstance(url, str)
    assert "chat/completions" in url
    assert "api-version=" in url
    assert captured["auth"] == "Bearer fake-token"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    # User prompt lists the candidate refs and constrains grounding.
    user = body["messages"][1]["content"]
    assert "object-storage.owner-tag.required" in user
    assert "Cite ONLY" in user


@pytest.mark.asyncio
async def test_gpt5_family_uses_completion_tokens_without_temperature() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope(_grounded_answer()))

    config = AzureOpenAIRcaModelConfig(
        endpoint="https://example.openai.azure.com",
        deployment="t2-rca",
        model_family="gpt-5.4-mini",
        system_prompt="You are an FDAI root-cause reasoner.",
        max_tokens=128,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIRcaModel(identity=_FakeIdentity(), http_client=client, config=config)
        await model.propose_cause(incident_summary="x", candidate_citations=_CANDIDATES)

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_completion_tokens"] == 128
    assert "max_tokens" not in body
    assert "temperature" not in body


@pytest.mark.asyncio
async def test_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIRcaModel(identity=_FakeIdentity(), http_client=client, config=_config())
        with pytest.raises(httpx.HTTPStatusError):
            await model.propose_cause(incident_summary="x", candidate_citations=_CANDIDATES)


@pytest.mark.asyncio
async def test_no_choices_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIRcaModel(identity=_FakeIdentity(), http_client=client, config=_config())
        with pytest.raises(RuntimeError, match="no choices"):
            await model.propose_cause(incident_summary="x", candidate_citations=_CANDIDATES)


@pytest.mark.asyncio
async def test_no_content_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIRcaModel(identity=_FakeIdentity(), http_client=client, config=_config())
        with pytest.raises(RuntimeError, match="no message content"):
            await model.propose_cause(incident_summary="x", candidate_citations=_CANDIDATES)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"endpoint": "ftp://x"}, "endpoint"),
        ({"deployment": ""}, "deployment"),
        ({"system_prompt": ""}, "system_prompt"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"timeout_seconds": 0.0}, "timeout_seconds"),
        ({"temperature": 3.0}, "temperature"),
    ],
)
def test_config_validation(kwargs: dict[str, object], match: str) -> None:
    base: dict[str, object] = {
        "endpoint": "https://example.openai.azure.com",
        "deployment": "gpt-4o-mini",
        "system_prompt": "s",
    }
    base.update(kwargs)
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    with pytest.raises(ValueError, match=match):
        AzureOpenAIRcaModel(
            identity=_FakeIdentity(),
            http_client=async_client,
            config=AzureOpenAIRcaModelConfig(**base),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_adapter_plugs_into_reasoner_and_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope(_grounded_answer()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = AzureOpenAIRcaModel(identity=_FakeIdentity(), http_client=client, config=_config())
        reasoner = LlmRcaReasoner(model=model)
        hypothesis = await reasoner.reason(
            incident_summary="disk near full", candidate_citations=_CANDIDATES
        )

    assert hypothesis is not None
    assert hypothesis.tier is RcaTier.T2
    assert hypothesis.citations[0].ref == "object-storage.owner-tag.required"
