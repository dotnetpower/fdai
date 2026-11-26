"""Azure Responses web-search adapter tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.core.web_search import WebSearchQuery
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.web_search import (
    AzureResponsesWebSearchConfig,
    AzureResponsesWebSearchError,
    AzureResponsesWebSearchProvider,
)
from fdai.shared.providers.workload_identity import IdentityToken

NOW = datetime(2026, 8, 25, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken("test-token", NOW + timedelta(minutes=5), audience)


def _envelope(
    *,
    url: str = "https://example.com/weather",
    source_url: str | None = None,
    start_index: int = 0,
    end_index: int = 14,
    include_tool: bool = True,
) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if include_tool:
        output.append(
            {
                "type": "web_search_call",
                "action": {
                    "sources": [{"type": "url", "url": source_url or url}],
                },
            }
        )
    output.append(
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Seoul is 21 C.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": url,
                            "title": "Weather source",
                            "start_index": start_index,
                            "end_index": end_index,
                        }
                    ],
                }
            ],
        }
    )
    return {"output": output}


def _provider(handler: httpx.MockTransport) -> tuple[AzureResponsesWebSearchProvider, _Identity]:
    identity = _Identity()
    provider = AzureResponsesWebSearchProvider(
        config=AzureResponsesWebSearchConfig(
            target=ModelRequestTarget(
                endpoint="https://models.example.azure.com",
                deployment="gpt-web-search",
                api_version="2025-04-01-preview",
            ),
            allowed_domains=("example.com",),
            max_results=3,
        ),
        identity=identity,
        http_client=httpx.AsyncClient(transport=handler),
        now=lambda: NOW,
    )
    return provider, identity


@pytest.mark.asyncio
async def test_web_search_posts_required_tool_and_projects_citations() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_envelope())

    provider, identity = _provider(httpx.MockTransport(respond))
    result = await provider.search(
        WebSearchQuery(
            text="current weather in Seoul",
            allowed_domains=("example.com",),
            max_results=3,
        )
    )

    request = requests[0]
    body = json.loads(request.content)
    assert request.url == "https://models.example.azure.com/openai/v1/responses"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert body["tool_choice"] == "required"
    assert body["include"] == ["web_search_call.action.sources"]
    assert body["tools"][0]["filters"] == {"allowed_domains": ["example.com"]}
    assert body["input"][1] == {"role": "user", "content": "current weather in Seoul"}
    assert identity.audiences == ["https://cognitiveservices.azure.com/.default"]
    assert result.answer == "Seoul is 21 C."
    assert result.snippets[0].url == "https://example.com/weather"
    assert result.citations[0].end_index == 14
    assert result.execution_receipt_digest is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    (
        _envelope(include_tool=False),
        _envelope(url="https://other.example.net/weather"),
        _envelope(url="http://example.com/weather"),
        _envelope(source_url="https://example.com/other"),
        _envelope(end_index=40),
    ),
)
async def test_web_search_rejects_unverified_or_invalid_citations(
    envelope: dict[str, Any],
) -> None:
    provider, _ = _provider(
        httpx.MockTransport(lambda _request: httpx.Response(200, json=envelope))
    )

    with pytest.raises(AzureResponsesWebSearchError):
        await provider.search(
            WebSearchQuery(
                text="current weather",
                allowed_domains=("example.com",),
                max_results=3,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "reason"),
    (
        (302, "provider_rejected"),
        (401, "provider_unauthorized"),
        (429, "provider_rate_limited"),
        (503, "provider_unavailable"),
    ),
)
async def test_web_search_fails_closed_without_following_redirects(
    status: int,
    reason: str,
) -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Location": "https://other.example.net/"})

    provider, _ = _provider(httpx.MockTransport(respond))

    with pytest.raises(AzureResponsesWebSearchError, match=reason):
        await provider.search(
            WebSearchQuery(
                text="current weather",
                allowed_domains=("example.com",),
                max_results=3,
            )
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_web_search_rejects_caller_domain_expansion_before_identity_io() -> None:
    provider, identity = _provider(
        httpx.MockTransport(lambda _request: httpx.Response(200, json=_envelope()))
    )

    with pytest.raises(AzureResponsesWebSearchError, match="domain_policy_mismatch"):
        await provider.search(
            WebSearchQuery(
                text="current weather",
                allowed_domains=("other.example.net",),
                max_results=3,
            )
        )
    assert identity.audiences == []


@pytest.mark.asyncio
async def test_duplicate_url_citations_bind_each_distinct_answer_span() -> None:
    url = "https://example.com/weather"
    envelope = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"sources": [{"type": "url", "url": url}]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Sunny and warm",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": url,
                                "title": "Weather source",
                                "start_index": 0,
                                "end_index": 5,
                            },
                            {
                                "type": "url_citation",
                                "url": url,
                                "title": "Weather source",
                                "start_index": 10,
                                "end_index": 14,
                            },
                        ],
                    }
                ],
            },
        ]
    }
    provider, _ = _provider(
        httpx.MockTransport(lambda _request: httpx.Response(200, json=envelope))
    )

    result = await provider.search(
        WebSearchQuery(
            text="current weather",
            allowed_domains=("example.com",),
            max_results=3,
        )
    )

    assert [snippet.text for snippet in result.snippets] == ["Sunny", "warm"]
    assert len({snippet.content_hash for snippet in result.snippets}) == 2
    assert [citation.source_hash for citation in result.citations] == [
        snippet.content_hash for snippet in result.snippets
    ]


@pytest.mark.asyncio
async def test_web_search_rejects_citation_url_userinfo() -> None:
    provider, _ = _provider(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json=_envelope(url="https://user:password@example.com/weather"),
            )
        )
    )

    with pytest.raises(AzureResponsesWebSearchError, match="no_valid_citations"):
        await provider.search(
            WebSearchQuery(
                text="current weather",
                allowed_domains=("example.com",),
                max_results=3,
            )
        )
