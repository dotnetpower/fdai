"""Twenty bounded KQL commands through the Command Deck route."""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_route
from fdai.delivery.read_api.routes.chat_log_query import LogQueryChatTools
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
