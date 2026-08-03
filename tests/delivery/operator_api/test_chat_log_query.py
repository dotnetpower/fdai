"""Twenty bounded KQL commands through the Command Deck route."""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.routes.chat import make_chat_route
from fdai.delivery.operator_api.routes.chat_log_query import (
    LogQueryChatTools,
    render_log_query_answer,
)
from fdai.delivery.operator_api.routes.chat_subscription_health import (
    SubscriptionHealthChatTools,
    needs_subscription_health,
)
from fdai.shared.providers.observation import LogQueryError, LogQueryResult


class RecordingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


class RecordingLogProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def query_log(
        self,
        *,
        query: str,
        window: str,
        max_rows: int = 100,
    ) -> LogQueryResult:
        self.calls.append({"query": query, "window": window, "max_rows": max_rows})
        rows = () if "TimeGenerated > now()" in query else ({"case": len(self.calls)},)
        return LogQueryResult(rows=rows, scanned_records=len(rows))


async def _allow(request: Request) -> str:
    return "reader"


QUERIES = (
    "print value=1",
    "Usage | where TimeGenerated > ago(1d) | summarize rows=count()",
    "Usage | where TimeGenerated > ago(1d) | summarize latest=max(TimeGenerated)",
    "Usage | summarize rows=count() by DataType | top 5 by rows desc",
    "Usage | summarize rows=count(), quantity=sum(Quantity) by IsBillable",
    "Usage | summarize quantity=sum(Quantity)",
    "Usage | summarize rows=count() by bin(TimeGenerated, 1h)",
    "Usage | where TimeGenerated > now() | take 1",
    'print payload=dynamic({}) | project value=tostring(payload["absent"])',
    'print message="한글 로그 확인"',
    'print message="operator\'s query"',
    'print payload=dynamic({"severity":"warning"}) | project severity=payload.severity',
    "Usage | summarize billable=countif(IsBillable == true), total=count()",
    'Usage | where DataType contains "data" | summarize rows=count()',
    "Usage | summarize quantity=sum(Quantity) by DataType | top 3 by quantity desc",
    "range row_id from 1 to 600 step 1 | project row_id",
    "union isfuzzy=true Usage, Heartbeat | summarize rows=count()",
    "search * | where TimeGenerated > ago(1h) | summarize rows=count()",
    "Usage | project TimeGenerated, DataType | order by TimeGenerated desc",
    "Usage | summarize rows=count() by SourceSystem",
)


def test_twenty_kql_commands_are_grounded_without_model_fallback() -> None:
    backend = RecordingBackend()
    provider = RecordingLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for query in QUERIES:
            response = client.post(
                "/chat",
                json={
                    "prompt": (f"query_log query={shlex.quote(query)} window=PT1H max_rows=20"),
                    "view_context": {},
                },
            )
            assert response.status_code == 200
            payload = response.json()
            verification = payload["verification"]
            assert verification["authority"] == "server_log_query"
            assert verification["status"] == "verified", query
            assert verification["reason_code"] == "log_query_bounded"
            assert verification["evidence_refs"][0].startswith("azure-monitor-logs:kql:")
            assert "azure_monitor_logs" in payload["answer"]

    assert len(provider.calls) == 20
    assert all(call["window"] == "PT1H" for call in provider.calls)
    assert all(call["max_rows"] == 20 for call in provider.calls)
    assert backend.calls == 0


def test_invalid_arguments_do_not_reach_provider() -> None:
    backend = RecordingBackend()
    provider = RecordingLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "query_log query=Usage window=PT1H max_rows=501"},
        )
    assert response.json()["verification"]["status"] == "unverified"
    assert provider.calls == []
    assert backend.calls == 0


def test_provider_failure_abstains_without_model_fallback() -> None:
    class FailingProvider:
        async def query_log(
            self, *, query: str, window: str, max_rows: int = 100
        ) -> LogQueryResult:
            raise LogQueryError("KQL syntax error")

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(FailingProvider()),
            )
        ]
    )
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": 'query_log query="Usage | where" window=PT1H'},
        )
    payload = response.json()
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "log_query_unavailable"
    assert "KQL syntax error" in payload["answer"]
    assert backend.calls == 0


def test_unconfigured_provider_abstains_without_model_fallback() -> None:
    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(None),
            )
        ]
    )
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "Find failed requests in the last 30 minutes by cause."},
        )
    payload = response.json()
    assert payload["verification"]["authority"] == "server_log_query"
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "log_query_unavailable"
    assert "not configured" in payload["answer"]
    assert backend.calls == 0


def test_non_log_command_preserves_principal_for_fallback() -> None:
    class RecordingFallback:
        principal_id: str | None = None

        async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
            self.principal_id = principal_id
            return {"tool": "fallback", "result": {"prompt": prompt}}

    fallback = RecordingFallback()
    provider = RecordingLogProvider()

    result = asyncio.run(
        LogQueryChatTools(provider, fallback=fallback).resolve(
            "query_inventory compute.vm",
            principal_id="reader-1",
        )
    )
    assert result == {"tool": "fallback", "result": {"prompt": "query_inventory compute.vm"}}
    assert fallback.principal_id == "reader-1"


def test_failed_request_questions_use_one_server_owned_log_template() -> None:
    prompts = (
        "최근 30분의 실패 요청을 원인별로 요약해줘.",
        "Find failed requests in the last 30 minutes and group them by cause.",
        "지난 30분간 실패한 요청을 결과 코드와 작업별로 묶어줘.",
        "Group request failures by operation and result code for the past 30 minutes.",
        "최근 반시간 요청 실패가 어디서 났는지 요약해.",
    )
    backend = RecordingBackend()
    provider = RecordingLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for prompt in prompts:
            response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
            assert response.status_code == 200
            payload = response.json()
            assert payload["verification"]["authority"] == "server_log_query"
            assert payload["verification"]["reason_code"] == "log_query_bounded"
            assert "root-cause proof" in payload["answer"] or "근본 원인" in payload["answer"]

    assert len(provider.calls) == len(prompts)
    assert {call["query"] for call in provider.calls} == {
        "AppRequests\n"
        '| where Success == false or ResultCode startswith "5"\n'
        "| summarize request_count=count(), first_seen=min(TimeGenerated), "
        "last_seen=max(TimeGenerated) by Name, ResultCode\n"
        "| top 20 by request_count desc"
    }
    assert {call["window"] for call in provider.calls} == {"PT30M"}
    assert {call["max_rows"] for call in provider.calls} == {20}
    assert backend.calls == 0


def test_signature_timeline_without_exact_signature_requests_clarification() -> None:
    prompts = (
        "이 오류가 처음 나타난 로그 시점은 언제야?",
        "When did this error signature first and most recently appear?",
        "이 에러의 최초와 최신 로그 시각을 찾아줘.",
        "Find the first and latest occurrence of this error.",
        "오류 시그니처가 언제 처음과 마지막으로 보였어?",
        "민감한 값을 노출하지 말고 관련 로그 예시를 보여줘.",
    )
    backend = RecordingBackend()
    provider = RecordingLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for prompt in prompts:
            response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
            payload = response.json()
            assert payload["verification"]["authority"] == "server_log_query"
            assert payload["verification"]["status"] == "unverified"
            assert (
                "exact error signature" in payload["answer"] or "정확한 오류" in payload["answer"]
            )

    assert provider.calls == []
    assert backend.calls == 0


def test_representative_log_questions_use_redacted_server_template() -> None:
    class SensitiveLogProvider(RecordingLogProvider):
        async def query_log(
            self,
            *,
            query: str,
            window: str,
            max_rows: int = 100,
        ) -> LogQueryResult:
            self.calls.append({"query": query, "window": window, "max_rows": max_rows})
            return LogQueryResult(
                rows=(
                    {
                        "message": (
                            "token=secret-value user@example.com 192.0.2.10 "
                            "https://example.com/private "
                            "00000000-0000-0000-0000-000000000000"
                        )
                    },
                ),
                scanned_records=1,
            )

    prompts = (
        "Show bounded representative logs with sensitive fields redacted.",
        "최근 오류 로그 샘플을 민감정보 제거해서 보여줘.",
        "Give me a small sanitized sample of recent error logs.",
    )
    backend = RecordingBackend()
    provider = SensitiveLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for prompt in prompts:
            response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
            payload = response.json()
            assert payload["verification"]["authority"] == "server_log_query"
            assert payload["verification"]["reason_code"] == "log_query_bounded"
            assert "[REDACTED]" in payload["answer"]
            assert "secret-value" not in payload["answer"]
            assert "user@example.com" not in payload["answer"]
            assert "192.0.2.10" not in payload["answer"]
            assert "https://example.com" not in payload["answer"]
            assert "00000000-0000-0000-0000-000000000000" not in payload["answer"]

    assert len(provider.calls) == len(prompts)
    assert len({call["query"] for call in provider.calls}) == 1
    assert {call["window"] for call in provider.calls} == {"PT30M"}
    assert {call["max_rows"] for call in provider.calls} == {20}
    assert backend.calls == 0


def test_trace_dependency_and_database_questions_use_server_templates() -> None:
    cohorts = {
        "trace_waterfall": (
            "가장 느린 분산 추적에서 병목 구간을 찾아줘.",
            "Show the slowest distributed trace and identify its bottleneck span.",
            "Which span is the bottleneck in the longest trace?",
        ),
        "dependency_latency": (
            "어떤 종속 서비스가 응답 지연을 만들었어?",
            "Which downstream dependency contributed most to latency?",
            "응답이 느려진 데 가장 크게 기여한 다운스트림을 찾아줘.",
        ),
        "database_slow_calls": (
            "데이터베이스 CPU 상승과 관련된 느린 쿼리를 찾아줘.",
            "Which database query best explains the CPU spike?",
            "Find the slow database calls associated with elevated CPU.",
        ),
    }
    backend = RecordingBackend()
    provider = RecordingLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for intent, prompts in cohorts.items():
            for prompt in prompts:
                response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
                payload = response.json()
                assert payload["verification"]["authority"] == "server_log_query"
                if intent == "database_slow_calls":
                    assert payload["verification"]["reason_code"] == "log_query_unavailable"
                    assert "resource" in payload["answer"]
                else:
                    assert payload["verification"]["reason_code"] == "log_query_bounded"
                    assert intent.replace("_", "-") in payload["answer"]

    assert len(provider.calls) == 6
    assert len({call["query"] for call in provider.calls}) == 2
    assert {call["window"] for call in provider.calls} == {"PT1H"}
    assert {call["max_rows"] for call in provider.calls} == {20}
    assert not needs_subscription_health("Which database query best explains the CPU spike?")
    assert not needs_subscription_health(
        "Quantify the customer and service-level impact of this incident."
    )
    assert backend.calls == 0


def test_pod_and_capacity_questions_hold_without_required_authority() -> None:
    class UnexpectedHealthProvider:
        calls = 0

        async def __call__(self, lookback_seconds: int) -> dict[str, Any]:
            del lookback_seconds
            self.calls += 1
            return {"status": "matched"}

    cohorts = {
        "selector": (
            "이 파드가 반복해서 재시작하는 이유가 뭐야?",
            "Why is this pod restarting or being throttled?",
            "이 pod의 재시작 원인을 찾아줘.",
        ),
        "capacity": (
            "현재 용량으로 트래픽 증가를 감당할 수 있어?",
            "Does this service have enough capacity for the observed load trend?",
            "Can current capacity handle the rising traffic?",
        ),
    }
    backend = RecordingBackend()
    provider = UnexpectedHealthProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for kind, prompts in cohorts.items():
            for prompt in prompts:
                response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
                payload = response.json()
                assert payload["verification"]["authority"] == "server_subscription_health"
                assert payload["verification"]["status"] == "unverified"
                expected = "pod name" if kind == "selector" else "capacity trend"
                assert expected in payload["answer"]

    assert provider.calls == 0
    assert backend.calls == 0


def test_bounded_error_query_questions_use_server_log_template() -> None:
    prompts = (
        "지난 15분의 오류를 찾는 안전한 KQL을 실행해줘.",
        "Run a bounded read-only query for errors from the last 15 minutes.",
        "Execute safe KQL for errors observed in the past 15 minutes.",
    )
    backend = RecordingBackend()
    provider = RecordingLogProvider()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=LogQueryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for prompt in prompts:
            response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
            payload = response.json()
            assert payload["verification"]["authority"] == "server_log_query"
            assert payload["verification"]["reason_code"] == "log_query_bounded"

    assert len(provider.calls) == len(prompts)
    assert len({call["query"] for call in provider.calls}) == 1
    assert {call["window"] for call in provider.calls} == {"PT15M"}
    assert {call["max_rows"] for call in provider.calls} == {20}
    assert backend.calls == 0


def test_contextual_database_pod_and_capacity_queries_use_exact_server_selector() -> None:
    async def run() -> None:
        provider = RecordingLogProvider()
        tools = LogQueryChatTools(provider)
        cases = (
            (
                "Which database query best explains the CPU spike?",
                "database_cpu_join",
                "AppDependencies",
                "database CPU and slow dependency calls",
            ),
            (
                "Why is this pod restarting or being throttled?",
                "pod_diagnosis",
                "KubePodInventory",
                "pod restart state",
            ),
            (
                "Does this service have enough capacity for the observed load trend?",
                "capacity_trend",
                "KubeNodeInventory",
                "current capacity cannot be confirmed",
            ),
        )
        for prompt, intent, query_token, answer_token in cases:
            evidence = await tools.resolve_with_context(
                prompt,
                principal_id="reader",
                context={
                    "resource_context": {
                        "name": "target-example",
                        "resource_type": "service.example",
                        "evidence_ref": "inventory:target-example",
                    }
                },
            )
            assert evidence is not None
            assert evidence["result"]["intent"] == intent
            assert query_token in provider.calls[-1]["query"]
            assert "target-example" in provider.calls[-1]["query"]
            answer = render_log_query_answer(evidence, locale="en")
            assert answer is not None
            assert answer_token in answer

    asyncio.run(run())


def test_contextual_diagnostic_holds_without_exact_resource_selector() -> None:
    async def run() -> None:
        provider = RecordingLogProvider()
        tools = LogQueryChatTools(provider)
        evidence = await tools.resolve_with_context(
            "Why is this pod restarting or being throttled?",
            principal_id="reader",
            context=None,
        )
        assert evidence is not None
        assert evidence["result"]["status"] == "clarification"
        assert evidence["result"]["reason"] == "exact_resource_selector_required"
        assert provider.calls == []

    asyncio.run(run())
