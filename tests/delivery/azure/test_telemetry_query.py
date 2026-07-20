"""Azure Monitor workspace adapters for RCA logs and distributed traces."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.telemetry_query import (
    AzureLogAnalyticsRcaLogProvider,
    AzureLogAnalyticsTraceProvider,
)
from fdai.shared.providers.log_query import LogQuery, LogQueryProviderError
from fdai.shared.providers.trace_query import TraceQuery, TraceQueryProviderError
from fdai.shared.providers.workload_identity import IdentityToken

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token", expires_at=_NOW + timedelta(hours=1), audience=audience
        )


def _provider(handler: object) -> AzureLogAnalyticsQueryProvider:
    return AzureLogAnalyticsQueryProvider(
        config=AzureLogAnalyticsQueryConfig(workspace_id="workspace-test"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
    )


def _table(columns: list[str], rows: list[list[object]]) -> dict[str, object]:
    return {
        "tables": [
            {
                "columns": [{"name": name, "type": "string"} for name in columns],
                "rows": rows,
            }
        ]
    }


@pytest.mark.asyncio
async def test_log_provider_builds_bounded_kql_and_maps_rows() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_table(
                ["at", "body", "severity", "service", "resource_id"],
                [["2026-07-20T11:59:00Z", "db failed", "3", "api", "resource-1"]],
            ),
        )

    provider = AzureLogAnalyticsRcaLogProvider(_provider(handler))
    records = [
        record
        async for record in provider.query(
            LogQuery(
                expression="failed' OR true",
                labels={"resource_id": "resource-1"},
                since=_NOW - timedelta(hours=1),
                until=_NOW,
                limit=20,
            )
        )
    ]
    assert len(records) == 1
    assert records[0].severity == "error"
    assert records[0].labels == {"resource_id": "resource-1"}
    body = json.loads(requests[0].content)
    assert "AppTraces" in body["query"]
    assert "failed'' OR true" in body["query"]
    assert body["query"].endswith("| take 21")
    assert body["timespan"] == "PT3600.000S"


@pytest.mark.asyncio
async def test_trace_provider_maps_requests_and_dependencies() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_table(
                [
                    "at",
                    "trace_id",
                    "span_id",
                    "parent_span_id",
                    "service",
                    "operation",
                    "duration_ms",
                    "success",
                    "resource_id",
                ],
                [
                    [
                        "2026-07-20T11:59:00Z",
                        "trace-1",
                        "span-1",
                        "",
                        "api",
                        "GET /",
                        250.0,
                        False,
                        "resource-1",
                    ]
                ],
            ),
        )

    provider = AzureLogAnalyticsTraceProvider(_provider(handler))
    spans = [
        span
        async for span in provider.query(
            TraceQuery(
                service="api",
                labels={"resource_id": "resource-1"},
                since=_NOW - timedelta(hours=1),
                until=_NOW,
                min_duration=timedelta(milliseconds=100),
                limit=10,
            )
        )
    ]
    assert len(spans) == 1
    assert spans[0].trace_id == "trace-1"
    assert spans[0].status == "error"
    assert spans[0].duration == timedelta(milliseconds=250)


@pytest.mark.parametrize(
    "query",
    [
        LogQuery(expression="", since=None, until=_NOW),
        LogQuery(expression="", since=_NOW, until=_NOW - timedelta(seconds=1)),
        LogQuery(
            expression="", labels={"tenant": "x"}, since=_NOW - timedelta(hours=1), until=_NOW
        ),
        LogQuery(expression="", since=_NOW - timedelta(hours=1), until=_NOW, limit=501),
    ],
)
@pytest.mark.asyncio
async def test_log_provider_rejects_unbounded_or_unsupported_queries(query: LogQuery) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unreached
        return httpx.Response(200, json=_table([], []))

    provider = AzureLogAnalyticsRcaLogProvider(_provider(handler))
    with pytest.raises(LogQueryProviderError):
        _ = [record async for record in provider.query(query)]


@pytest.mark.asyncio
async def test_trace_provider_normalizes_backend_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad query")

    provider = AzureLogAnalyticsTraceProvider(_provider(handler))
    with pytest.raises(TraceQueryProviderError, match="trace query failed"):
        _ = [
            span
            async for span in provider.query(
                TraceQuery(since=_NOW - timedelta(hours=1), until=_NOW)
            )
        ]
