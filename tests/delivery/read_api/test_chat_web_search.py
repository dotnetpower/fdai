from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation.answer_plan import build_answer_plan
from fdai.core.web_search import WebSearchQuery, WebSearchResult, WebSnippet
from fdai.delivery.azure.web_search import AzureWebSearchRequestError
from fdai.delivery.read_api.routes.chat import make_chat_health_route, make_chat_route
from fdai.delivery.read_api.routes.chat_web_search import (
    ChatWebSearchConfig,
    ChatWebSearchResolver,
    _classify_search_intent,
    chat_web_search_from_env,
)


@dataclass(frozen=True, slots=True)
class SearchIntentRubricCase:
    name: str
    prompt: str
    expected_route: str
    expected_confidence: float


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
        1.0,
    ),
    SearchIntentRubricCase(
        "audit-local",
        "감사 로그에서 실패한 작업을 찾아봐",
        "local",
        1.0,
    ),
    SearchIntentRubricCase("definition", "MTTR이 뭐야?", "none", 1.0),
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


class _BlockedProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        self.calls += 1
        raise AzureWebSearchRequestError("tool_blocked")

    async def check_readiness(self, query: WebSearchQuery) -> str:
        await self.search(query)
        raise AssertionError("unreachable")


class _IntentClassifier:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[str] = []

    async def classify_intent(self, prompt: str, *, budget_ms: int) -> dict[str, object]:
        self.calls.append(prompt)
        assert budget_ms >= 1
        return dict(self.result)


class _RubricIntentClassifier:
    async def classify_intent(self, prompt: str, *, budget_ms: int) -> dict[str, object]:
        assert budget_ms >= 1
        if "Grafana" in prompt:
            return {
                "route": "web",
                "confidence": 0.95,
                "reason": "explicit_public_search",
                "query": "Grafana alternatives",
                "goal": "alternatives",
                "subject": "Grafana",
                "capabilities": [
                    "metrics visualization",
                    "observability dashboards",
                ],
            }
        return {
            "route": "none",
            "confidence": 0.95,
            "reason": "no_search_intent",
            "query": "",
            "goal": "none",
            "subject": "",
            "capabilities": [],
        }


class _FailingIntentClassifier:
    async def classify_intent(self, prompt: str, *, budget_ms: int) -> dict[str, object]:
        raise AssertionError("planned web search must not reclassify natural language")


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


def _write_resolved_models(path: Path, *, include_web_search: bool) -> None:
    candidate = {
        "endpoint": "https://example-openai.openai.azure.com/",
        "deployment": "websearch-gpt-4-1-mini",
        "api_version": "2024-08-01-preview",
    }
    payload: dict[str, object] = {
        "narrator_candidates": [{**candidate, "deployment": "narrator-gpt-4-1-mini"}]
    }
    if include_web_search:
        payload["web_search_candidates"] = [candidate]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_web_search_factory_uses_dedicated_candidates(tmp_path: Path) -> None:
    resolved_path = tmp_path / "resolved-models.json"
    _write_resolved_models(resolved_path, include_web_search=True)

    resolver = chat_web_search_from_env(
        {
            "FDAI_WEB_SEARCH_ENABLED": "1",
            "FDAI_WEB_SEARCH_ALLOWED_DOMAINS": "learn.microsoft.com",
            "LLM_RESOLVED_MODELS_PATH": str(resolved_path),
        }
    )

    assert resolver is not None
    assert resolver.descriptor()["router"]["chose"] == "websearch-gpt-4-1-mini"


def test_web_search_factory_rejects_narrator_only_artifact(tmp_path: Path) -> None:
    resolved_path = tmp_path / "resolved-models.json"
    _write_resolved_models(resolved_path, include_web_search=False)

    with pytest.raises(ValueError, match="no web-search candidates"):
        chat_web_search_from_env(
            {
                "FDAI_WEB_SEARCH_ENABLED": "1",
                "FDAI_WEB_SEARCH_ALLOWED_DOMAINS": "learn.microsoft.com",
                "LLM_RESOLVED_MODELS_PATH": str(resolved_path),
            }
        )


def test_web_search_factory_prefers_configured_foundry_agent(tmp_path: Path) -> None:
    resolved_path = tmp_path / "resolved-models.json"
    _write_resolved_models(resolved_path, include_web_search=True)

    resolver = chat_web_search_from_env(
        {
            "FDAI_WEB_SEARCH_ENABLED": "1",
            "FDAI_WEB_SEARCH_ALLOWED_DOMAINS": "learn.microsoft.com",
            "FDAI_WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT": (
                "https://example.services.ai.azure.com/api/projects/example"
            ),
            "FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME": "fdai-web-search",
            "LLM_RESOLVED_MODELS_PATH": str(resolved_path),
        }
    )

    assert resolver is not None
    assert resolver.descriptor()["router"]["chose"] == "foundry-agent:fdai-web-search"


def test_web_search_factory_rejects_partial_foundry_configuration(tmp_path: Path) -> None:
    resolved_path = tmp_path / "resolved-models.json"
    _write_resolved_models(resolved_path, include_web_search=True)

    with pytest.raises(ValueError, match="MUST be configured together"):
        chat_web_search_from_env(
            {
                "FDAI_WEB_SEARCH_ENABLED": "1",
                "FDAI_WEB_SEARCH_ALLOWED_DOMAINS": "learn.microsoft.com",
                "FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME": "fdai-web-search",
                "LLM_RESOLVED_MODELS_PATH": str(resolved_path),
            }
        )


async def test_normal_screen_question_does_not_search() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve("What does this screen show?", {})

    assert evidence is None
    assert provider.calls == []


async def test_planned_web_search_bypasses_natural_language_classifiers() -> None:
    provider = _Provider()
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=_FailingIntentClassifier(),
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )

    evidence = await resolver.resolve_planned(
        {"query": "current Azure SDK release", "goal": "current_fact"},
        {},
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert len(provider.calls) == 1
    assert provider.calls[0].text == "current Azure SDK release"


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


async def test_blocked_provider_returns_stable_unavailable_reason() -> None:
    provider = _BlockedProvider()
    resolver = ChatWebSearchResolver(
        provider=provider,
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )

    evidence = await resolver.resolve(
        "Search the web for the latest Azure SDK version.",
        {},
    )

    assert evidence == {
        "status": "unavailable",
        "reason": "tool_blocked",
        "sources": [],
    }


async def test_readiness_marks_blocked_tool_unavailable_without_retrying() -> None:
    provider = _BlockedProvider()
    resolver = ChatWebSearchResolver(
        provider=provider,
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )

    assert await resolver.verify_availability() is False
    assert resolver.descriptor()["available"] is False
    assert resolver.descriptor()["unavailable_reason"] == "tool_blocked"

    evidence = await resolver.resolve(
        "Search the web for the latest Azure SDK version.",
        {},
    )

    assert evidence == {
        "status": "unavailable",
        "reason": "tool_blocked",
        "sources": [],
    }
    assert provider.calls == 1


async def test_explicit_search_can_fill_gap_after_internal_evidence() -> None:
    provider = _Provider()

    evidence = await _resolver(provider).resolve(
        "Search the web for the latest Azure SDK release.",
        {"_agent_evidence": {"answer": "internal"}},
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert len(provider.calls) == 1


async def test_semantic_classifier_routes_unlisted_english_search_request() -> None:
    provider = _Provider()
    classifier = _IntentClassifier(
        {
            "route": "web",
            "confidence": 0.93,
            "reason": "explicit_public_search",
            "query": "current MTTR platforms",
            "goal": "research",
            "subject": "",
            "capabilities": [],
        }
    )
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=classifier,
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )

    prompt = "Could you source current MTTR platforms?"
    evidence = await resolver.resolve(prompt, {"_answer_plan": build_answer_plan(prompt).to_dict()})

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert classifier.calls == ["Could you source current MTTR platforms?"]
    assert len(provider.calls) == 1
    assert provider.calls[0].text == "current MTTR platforms"


async def test_alternative_search_carries_goal_and_subject_to_provider() -> None:
    provider = _Provider()
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=_IntentClassifier(
            {
                "route": "web",
                "confidence": 0.96,
                "reason": "explicit_public_search",
                "query": "solutions similar to FDAI",
                "goal": "alternatives",
                "subject": "FDAI",
                "capabilities": [
                    "autonomous cloud operations",
                    "incident response automation",
                    "change risk management",
                    "FinOps cost optimization",
                ],
            }
        ),
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )
    prompt = "FDAI와 비슷한 솔루션을 검색해줘"

    evidence = await resolver.resolve(prompt, {"_answer_plan": build_answer_plan(prompt).to_dict()})

    assert evidence is not None
    assert len(provider.calls) == 1
    assert provider.calls[0].metadata["goal"] == "alternatives"
    assert provider.calls[0].metadata["subject"] == "FDAI"
    assert "FDAI" not in provider.calls[0].text
    assert "incident response automation" in provider.calls[0].text


async def test_alternative_search_does_not_fallback_to_raw_query() -> None:
    provider = _Provider()
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=_IntentClassifier(
            {
                "route": "none",
                "confidence": 0.95,
                "reason": "no_search_intent",
                "query": "",
                "goal": "none",
                "subject": "",
                "capabilities": [],
            }
        ),
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )
    prompt = "FDAI와 비슷한 솔루션을 검색해줘"

    evidence = await resolver.resolve(prompt, {"_answer_plan": build_answer_plan(prompt).to_dict()})

    assert evidence is None
    assert provider.calls == []


async def test_semantic_classifier_cannot_override_local_or_sensitive_boundaries() -> None:
    provider = _Provider()
    classifier = _IntentClassifier(
        {
            "route": "web",
            "confidence": 0.99,
            "reason": "explicit_public_search",
            "query": "failed actions",
            "goal": "research",
            "subject": "",
            "capabilities": [],
        }
    )
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=classifier,
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )
    context = {"_answer_plan": {"intent": "open_question"}}

    local = await resolver.resolve("Search this screen for failures", context)
    sensitive = await resolver.resolve(
        "Could you source details for 00000000-0000-0000-0000-000000000000?",
        context,
    )

    assert local is None
    assert sensitive is None
    assert classifier.calls == []
    assert provider.calls == []


async def test_semantic_classifier_fails_closed_on_local_low_confidence_or_malformed() -> None:
    context = {"_answer_plan": {"intent": "open_question"}}
    results = (
        {
            "route": "local",
            "confidence": 0.95,
            "reason": "local_scope",
            "query": "",
            "goal": "local",
            "subject": "",
            "capabilities": [],
        },
        {
            "route": "web",
            "confidence": 0.69,
            "reason": "ambiguous",
            "query": "MTTR platforms",
            "goal": "research",
            "subject": "",
            "capabilities": [],
        },
        {
            "route": "web",
            "confidence": "high",
            "reason": "ambiguous",
            "query": "MTTR platforms",
            "goal": "research",
            "subject": "",
            "capabilities": [],
        },
    )

    for result in results:
        provider = _Provider()
        resolver = ChatWebSearchResolver(
            provider=provider,
            intent_classifier=_IntentClassifier(result),
            config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
        )

        evidence = await resolver.resolve("Recommend suitable MTTR platforms", context)

        assert evidence is None
        assert provider.calls == []


async def test_semantic_normalized_query_is_rechecked_for_sensitive_identifiers() -> None:
    provider = _Provider()
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=_IntentClassifier(
            {
                "route": "web",
                "confidence": 0.95,
                "reason": "explicit_public_search",
                "query": "subscription 00000000-0000-0000-0000-000000000000",
                "goal": "research",
                "subject": "",
                "capabilities": [],
            }
        ),
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )

    evidence = await resolver.resolve(
        "Could you source the related service?",
        {"_answer_plan": {"intent": "open_question"}},
    )

    assert evidence == {
        "status": "skipped",
        "reason": "query_not_public_safe",
        "sources": [],
    }
    assert provider.calls == []


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
    resolver = ChatWebSearchResolver(
        provider=provider,
        intent_classifier=_RubricIntentClassifier(),
        config=ChatWebSearchConfig(allowed_domains=("learn.microsoft.com",)),
    )
    failures: list[str] = []
    for case in SEARCH_INTENT_RUBRIC_CASES:
        calls_before = len(provider.calls)
        decision = _classify_search_intent(case.prompt)
        evidence = await resolver.resolve(
            case.prompt,
            {"_answer_plan": build_answer_plan(case.prompt).to_dict()},
        )
        expected_provider_calls = 1 if case.expected_route == "web" else 0
        provider_calls = len(provider.calls) - calls_before
        if (
            decision.route != case.expected_route
            or decision.confidence != case.expected_confidence
            or provider_calls != expected_provider_calls
            or (case.expected_route == "web") != (evidence is not None)
        ):
            failures.append(
                f"{case.name}: expected {case.expected_route}/{case.expected_confidence}, "
                f"got {decision.route}/{decision.confidence}, provider_calls={provider_calls}"
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
