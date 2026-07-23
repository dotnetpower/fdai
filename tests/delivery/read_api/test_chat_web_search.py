from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.web_search import WebSearchQuery, WebSearchResult, WebSnippet
from fdai.delivery.read_api.routes.chat import make_chat_health_route, make_chat_route
from fdai.delivery.read_api.routes.chat_web_search import (
    ChatWebSearchConfig,
    ChatWebSearchResolver,
    _classify_search_intent,
)


@dataclass(frozen=True, slots=True)
class SearchIntentRubricCase:
    name: str
    prompt: str
    expected_route: str
    expected_score: float


SEARCH_INTENT_RUBRIC_CASES = (
    SearchIntentRubricCase("explicit-ko", "MTTR 솔루션을 검색해줘", "web", 1.0),
    SearchIntentRubricCase("natural-ko", "MTTR 도구 좀 찾아봐", "web", 1.0),
    SearchIntentRubricCase("colloquial-ko", "Grafana 대안을 구글링해줘", "web", 1.0),
    SearchIntentRubricCase("implicit-fresh-ko", "요즘 MTTR 도구 뭐가 좋아?", "web", 0.8),
    SearchIntentRubricCase("web-context-ko", "웹에서 MTTR 솔루션 뭐가 있어?", "web", 1.0),
    SearchIntentRubricCase("english-discovery", "Find current MTTR platforms", "web", 1.0),
    SearchIntentRubricCase(
        "latest-public",
        "What is the latest Azure SDK release?",
        "web",
        0.8,
    ),
    SearchIntentRubricCase(
        "screen-local",
        "이 화면에서 MTTR 솔루션을 검색해줘",
        "local",
        0.0,
    ),
    SearchIntentRubricCase(
        "audit-local",
        "감사 로그에서 실패한 작업을 찾아봐",
        "local",
        0.0,
    ),
    SearchIntentRubricCase("definition", "MTTR이 뭐야?", "none", 0.0),
)


class _Provider:
    def __init__(self) -> None:
        self.calls: list[WebSearchQuery] = []

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        self.calls.append(query)
        return WebSearchResult(
            query=query,
            snippets=(
                WebSnippet(
                    url="https://learn.microsoft.com/release",
                    domain="learn.microsoft.com",
                    title="Release notes",
                    text="The latest SDK release is version 2.",
                    content_hash="sha256:web",
                    fetched_at=datetime.now(tz=UTC),
                ),
            ),
        )


class _Backend:
    def __init__(self) -> None:
        self.view_context: dict[str, Any] | None = None

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        self.view_context = view_context
        return {"answer": "The latest SDK release is version 2.", "model": "mini-fast"}


async def _allow(_: Request) -> str:
    return "reader"


def _resolver(provider: _Provider) -> ChatWebSearchResolver:
    return ChatWebSearchResolver(
        provider=provider,
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )


async def test_normal_screen_question_does_not_search() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve("What does this screen show?", {})

    assert evidence is None
    assert provider.calls == []


async def test_latest_public_fact_searches_and_returns_sanitized_evidence() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "What is the latest Azure SDK version?",
        {},
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert len(provider.calls) == 1
    assert provider.calls[0].metadata["tier"] == "chat-t2"
    assert evidence["snippets"][0].startswith('<web_snippet trusted="false"')


async def test_explicit_search_can_fill_gap_after_internal_evidence() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "Search the web for the latest Azure SDK release.",
        {"_agent_evidence": {"answer": "internal"}},
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert len(provider.calls) == 1


def test_natural_korean_public_discovery_requests_search_the_web() -> None:
    assert _classify_search_intent("유사한 서비스가 있는지 검색해줄래?").route == "web"
    assert _classify_search_intent("인터넷에서 유사한 서비스를 검색해줄래?").route == "web"
    assert _classify_search_intent("MTTR 과 관련된 솔루션에 대해서 검색해봐").route == "web"


def test_current_screen_search_does_not_search_the_web() -> None:
    assert _classify_search_intent("이 화면에서 실패한 작업을 검색해줄래?").route == "local"
    assert _classify_search_intent("이 화면에서 MTTR 솔루션을 검색해줄래?").route == "local"


def test_public_database_tool_search_does_not_become_local_scope() -> None:
    decision = _classify_search_intent("Search for database monitoring tools")

    assert decision.route == "web"
    assert decision.reason == "explicit_search_request"


async def test_ten_copilot_reference_search_intents_score_ten_of_ten() -> None:
    provider = _Provider()
    resolver = _resolver(provider)
    failures: list[str] = []
    for case in SEARCH_INTENT_RUBRIC_CASES:
        calls_before = len(provider.calls)
        decision = _classify_search_intent(case.prompt)
        evidence = await resolver.resolve(case.prompt, {})
        expected_provider_calls = 1 if case.expected_route == "web" else 0
        provider_calls = len(provider.calls) - calls_before
        if (
            decision.route != case.expected_route
            or decision.novelty_score != case.expected_score
            or provider_calls != expected_provider_calls
            or (case.expected_route == "web") != (evidence is not None)
        ):
            failures.append(
                f"{case.name}: expected {case.expected_route}/{case.expected_score}, "
                f"got {decision.route}/{decision.novelty_score}, provider_calls={provider_calls}"
            )

    passed = len(SEARCH_INTENT_RUBRIC_CASES) - len(failures)
    assert not failures, f"Copilot-reference search rubric {passed}/10\n" + "\n".join(failures)


async def test_sensitive_query_is_blocked_before_provider_call() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "Search the web for subscription 00000000-0000-0000-0000-000000000000",
        {},
    )

    assert evidence == {
        "status": "skipped",
        "reason": "query_not_public_safe",
        "sources": [],
    }
    assert provider.calls == []


def test_chat_route_injects_and_surfaces_public_web_evidence() -> None:
    provider = _Provider()
    resolver = _resolver(provider)
    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                web_search_resolver=resolver,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Search the web for the latest Azure SDK release.",
            "view_context": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert backend.view_context is not None
    assert backend.view_context["_web_evidence"]["status"] == "matched"
    assert payload["web_search"]["status"] == "matched"
    assert payload["web_search"]["sources"][0]["url"] == ("https://learn.microsoft.com/release")
    assert payload["verification"]["authority"] == "public_web_snapshot"


def test_chat_health_describes_web_search_without_exposing_snippets() -> None:
    resolver = _resolver(_Provider())
    app = Starlette(
        routes=[
            make_chat_health_route(
                backend=_Backend(),
                authorize=_allow,
                web_search_resolver=resolver,
            )
        ]
    )

    payload = TestClient(app).get("/chat/health").json()

    assert payload["web_search"]["available"] is True
    assert payload["web_search"]["allowed_domains"] == ["learn.microsoft.com"]
    assert "snippets" not in payload["web_search"]
