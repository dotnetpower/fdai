from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from fdai.core.web_search import WebSearchQuery, WebSearchResult, WebSnippet
from fdai.delivery.azure.web_search import (
    AzureResponsesWebSearchCandidate,
    AzureResponsesWebSearchConfig,
    LatencyRoutedWebSearchProvider,
)
from fdai.delivery.azure.web_search_response import _alternative_source_allowed
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
            audience=audience,
        )


class _Candidate:
    def __init__(
        self,
        *,
        delay_ms: int,
        fail_search: bool = False,
        empty_search: bool = False,
        fail_intent: bool = False,
        intent_route: str = "none",
    ) -> None:
        self.delay_ms = delay_ms
        self.fail_search = fail_search
        self.empty_search = empty_search
        self.fail_intent = fail_intent
        self.intent_route = intent_route
        self.search_calls = 0
        self.intent_calls = 0
        self.probe_calls = 0

    async def probe(self) -> None:
        self.probe_calls += 1
        await asyncio.sleep(self.delay_ms / 1000)

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        self.search_calls += 1
        await asyncio.sleep(self.delay_ms / 1000)
        if self.fail_search:
            raise RuntimeError("candidate failed")
        if self.empty_search:
            return WebSearchResult(query=query, reasons=("no_search_citations",))
        snippet = WebSnippet(
            url="https://docs.example.com/release",
            domain="docs.example.com",
            title="Release notes",
            text="The current release is available.",
            content_hash="sha256:test",
            fetched_at=datetime.now(tz=UTC),
        )
        return WebSearchResult(query=query, snippets=(snippet,))

    async def classify_intent(
        self,
        prompt: str,  # noqa: ARG002
        *,
        budget_ms: int,  # noqa: ARG002
    ) -> dict[str, object]:
        self.intent_calls += 1
        if self.fail_intent:
            raise RuntimeError("intent candidate failed")
        return {
            "route": self.intent_route,
            "confidence": 0.9,
            "reason": "test_intent",
            "query": "current MTTR platforms" if self.intent_route == "web" else "",
            "goal": "research" if self.intent_route == "web" else "none",
            "subject": "",
            "capabilities": [],
        }


async def test_latency_router_benchmarks_and_prefers_fastest_candidate() -> None:
    slow = _Candidate(delay_ms=20)
    fast = _Candidate(delay_ms=1)
    provider = LatencyRoutedWebSearchProvider(candidates=[("slow", slow), ("fast", fast)])

    chose = await provider.benchmark()
    result = await provider.search(
        WebSearchQuery(text="latest release", allowed_domains=("docs.example.com",))
    )

    assert chose == "fast"
    assert fast.search_calls == 1
    assert slow.search_calls == 0
    assert "model:fast" in result.reasons


async def test_latency_router_fails_over_when_fastest_candidate_errors() -> None:
    failing = _Candidate(delay_ms=1, fail_search=True)
    healthy = _Candidate(delay_ms=15)
    provider = LatencyRoutedWebSearchProvider(
        candidates=[("failing", failing), ("healthy", healthy)]
    )
    await provider.benchmark()

    result = await provider.search(
        WebSearchQuery(text="latest release", allowed_domains=("docs.example.com",))
    )

    assert failing.search_calls == 1
    assert healthy.search_calls == 1
    assert "model:healthy" in result.reasons


async def test_latency_router_fails_over_when_fastest_candidate_has_no_snippets() -> None:
    empty = _Candidate(delay_ms=1, empty_search=True)
    healthy = _Candidate(delay_ms=15)
    provider = LatencyRoutedWebSearchProvider(candidates=[("empty", empty), ("healthy", healthy)])
    await provider.benchmark()

    result = await provider.search(
        WebSearchQuery(text="MTTR solutions", allowed_domains=("docs.example.com",))
    )

    assert empty.search_calls == 1
    assert healthy.search_calls == 1
    assert "model:healthy" in result.reasons


async def test_latency_router_fails_over_when_intent_candidate_errors() -> None:
    failing = _Candidate(delay_ms=1, fail_intent=True)
    healthy = _Candidate(delay_ms=15, intent_route="web")
    provider = LatencyRoutedWebSearchProvider(
        candidates=[("failing", failing), ("healthy", healthy)]
    )
    await provider.benchmark()

    result = await provider.classify_intent("source current MTTR platforms", budget_ms=1_000)

    assert failing.intent_calls == 1
    assert healthy.intent_calls == 1
    assert result["route"] == "web"


async def test_azure_candidate_enforces_filters_and_parses_citations() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Version 2 is the latest release. More details follow.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "start_index": 0,
                                        "end_index": 32,
                                        "url": "https://docs.example.com/release",
                                        "title": "Release notes",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 34,
                                        "end_index": 53,
                                        "url": "https://offlist.example.net/post",
                                        "title": "Off-list",
                                    },
                                ],
                            }
                        ],
                    },
                ]
            },
        )

    candidate = AzureResponsesWebSearchCandidate(
        config=AzureResponsesWebSearchConfig(
            endpoint="https://example.openai.azure.com",
            deployment="mini-fast",
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await candidate.search(
        WebSearchQuery(
            text="latest release",
            allowed_domains=("docs.example.com",),
            max_results=3,
        )
    )

    assert captured["authorization"] == "Bearer test-token"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["tools"][0]["filters"]["allowed_domains"] == ["docs.example.com"]
    assert [snippet.url for snippet in result.snippets] == ["https://docs.example.com/release"]
    assert result.snippets[0].text == "Version 2 is the latest release."


async def test_azure_candidate_classifies_multilingual_search_intent_as_strict_json() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "route": "web",
                        "confidence": 0.94,
                        "reason": "explicit_public_search",
                        "query": "current Grafana alternatives",
                        "goal": "alternatives",
                        "subject": "Grafana",
                        "capabilities": [
                            "metrics visualization",
                            "observability dashboards",
                        ],
                    }
                )
            },
        )

    candidate = AzureResponsesWebSearchCandidate(
        config=AzureResponsesWebSearchConfig(
            endpoint="https://example.openai.azure.com",
            deployment="mini-fast",
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await candidate.classify_intent(
        "¿Puedes investigar alternativas a Grafana?",
        budget_ms=1_000,
    )

    assert result == {
        "route": "web",
        "confidence": 0.94,
        "reason": "explicit_public_search",
        "query": "current Grafana alternatives",
        "goal": "alternatives",
        "subject": "Grafana",
        "capabilities": [
            "metrics visualization",
            "observability dashboards",
        ],
    }
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["input"][1]["role"] == "user"
    assert "¿Puedes investigar alternativas a Grafana?" in body["input"][1]["content"]


async def test_alternative_search_drops_self_and_generic_vendor_sources() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        answer = (
            "FDAI docs. Azure home. Cloud Adoption Framework. Resiliency Documentation. "
            "Azure Brain blog. Azure SRE Agent. Datadog Watchdog."
        )
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": answer,
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "start_index": 0,
                                        "end_index": 10,
                                        "url": "https://github.com/dotnetpower/fdai/blob/main/README.md",
                                        "title": "FDAI README",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 11,
                                        "end_index": 22,
                                        "url": "https://azure.microsoft.com/en-us/",
                                        "title": "Microsoft Azure",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 23,
                                        "end_index": 48,
                                        "url": "https://learn.microsoft.com/azure/cloud-adoption-framework/strategy/",
                                        "title": "Cloud Adoption Framework strategy",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 49,
                                        "end_index": 74,
                                        "url": "https://learn.microsoft.com/en-us/azure/resiliency/",
                                        "title": "Resiliency Documentation",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 75,
                                        "end_index": 92,
                                        "url": "https://azure.microsoft.com/en-us/blog/meet-brain/",
                                        "title": (
                                            "Meet Brain: The AI system behind Azure reliability"
                                        ),
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 93,
                                        "end_index": 109,
                                        "url": "https://learn.microsoft.com/azure/sre-agent/",
                                        "title": "Azure SRE Agent",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 110,
                                        "end_index": len(answer),
                                        "url": "https://docs.datadoghq.com/watchdog/",
                                        "title": "Datadog Watchdog",
                                    },
                                ],
                            }
                        ],
                    },
                ]
            },
        )

    candidate = AzureResponsesWebSearchCandidate(
        config=AzureResponsesWebSearchConfig(
            endpoint="https://example.openai.azure.com",
            deployment="mini-fast",
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await candidate.search(
        WebSearchQuery(
            text="autonomous cloud operations AIOps platforms",
            allowed_domains=(
                "github.com",
                "azure.microsoft.com",
                "learn.microsoft.com",
                "docs.datadoghq.com",
            ),
            metadata={"goal": "alternatives", "subject": "FDAI"},
        )
    )

    assert [snippet.title for snippet in result.snippets] == [
        "Azure SRE Agent",
        "Datadog Watchdog",
    ]
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["tools"][0]["search_context_size"] == "medium"
    assert "at least three distinct operational AIOps products" in body["input"]
    rubric = {
        "matched": bool(result.snippets),
        "candidate-count": len(result.snippets) >= 2,
        "self-url-excluded": all("/fdai" not in item.url.casefold() for item in result.snippets),
        "self-title-excluded": all("fdai" not in item.title.casefold() for item in result.snippets),
        "generic-homepage-excluded": all(
            bool([part for part in urlsplit(item.url).path.split("/") if part])
            for item in result.snippets
        ),
        "conceptual-guidance-excluded": all(
            not any(
                term in item.title.casefold()
                for term in ("framework", "strategy", "what is", "documentation")
            )
            for item in result.snippets
        ),
        "distinct-domains": len({item.domain for item in result.snippets}) >= 2,
        "direct-titles": all(item.title for item in result.snippets),
        "goal-preserved": result.query.metadata.get("goal") == "alternatives",
        "subject-preserved": result.query.metadata.get("subject") == "FDAI",
    }
    assert all(rubric.values()), (
        f"alternatives relevance rubric {sum(rubric.values())}/10: "
        + ", ".join(name for name, passed in rubric.items() if not passed)
    )


def test_short_subject_does_not_false_match_longer_product_terms() -> None:
    assert _alternative_source_allowed(
        "https://docs.datadoghq.com/watchdog/",
        "Datadog AIOps Watchdog",
        subject="AI",
    )


async def test_alternative_search_requires_two_distinct_product_identities() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Watchdog overview. Watchdog RCA.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "start_index": 0,
                                        "end_index": 18,
                                        "url": "https://docs.datadoghq.com/watchdog/",
                                        "title": "Datadog Watchdog",
                                    },
                                    {
                                        "type": "url_citation",
                                        "start_index": 19,
                                        "end_index": 32,
                                        "url": "https://docs.datadoghq.com/watchdog/rca/",
                                        "title": "Datadog Watchdog RCA",
                                    },
                                ],
                            }
                        ],
                    },
                ]
            },
        )

    candidate = AzureResponsesWebSearchCandidate(
        config=AzureResponsesWebSearchConfig(
            endpoint="https://example.openai.azure.com",
            deployment="mini-fast",
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await candidate.search(
        WebSearchQuery(
            text="AIOps incident response products",
            allowed_domains=("docs.datadoghq.com",),
            metadata={"goal": "alternatives", "subject": "FDAI"},
        )
    )

    assert result.snippets == ()
    assert "insufficient_comparable_sources" in result.reasons
