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
from fdai.delivery.azure.telemetry_workspace import AzureTelemetryWorkspaceResolution
from fdai.shared.providers.log_query import LogQuery, LogQueryProviderError
from fdai.shared.providers.trace_query import TraceQuery, TraceQueryProviderError
from fdai.shared.providers.workload_identity import IdentityToken

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token", expires_at=_NOW + timedelta(hours=1), audience=audience
        )


class _WorkspaceResolver:
    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime,
    ) -> AzureTelemetryWorkspaceResolution:
        assert resource_ref == "resource-neutral"
        assert at == _NOW
        return AzureTelemetryWorkspaceResolution(
            provider_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000000/"
                "resourceGroups/rg-example/providers/Microsoft.Web/sites/app-example"
            ),
            inventory_generation="inventory-generation",
            workspace_ids=("00000000-0000-0000-0000-000000000000",),
        )


class _StaticWorkspaceResolver:
    def __init__(self, workspace_ids: tuple[str, ...]) -> None:
        self._workspace_ids = workspace_ids

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime,
    ) -> AzureTelemetryWorkspaceResolution:
        del resource_ref, at
        return AzureTelemetryWorkspaceResolution(
            provider_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000000/"
                "resourceGroups/rg-example/providers/Microsoft.Web/sites/app-example"
            ),
            inventory_generation="inventory-generation",
            workspace_ids=self._workspace_ids,
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
async def test_log_provider_filters_exact_pod_uid_across_app_and_container_logs() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_table(
                ["at", "body", "severity", "service", "resource_id", "pod_uid", "source"],
                [
                    [
                        "2026-07-20T11:59:00Z",
                        "runtime line",
                        "error",
                        "api",
                        "",
                        "pod-uid-a",
                        "ContainerLogV2",
                    ]
                ],
            ),
        )

    provider = AzureLogAnalyticsRcaLogProvider(_provider(handler))
    records = [
        record
        async for record in provider.query(
            LogQuery(
                expression="",
                labels={"pod_uid": "pod-uid-a"},
                since=_NOW - timedelta(hours=1),
                until=_NOW,
                limit=20,
            )
        )
    ]

    assert records[0].labels == {"pod_uid": "pod-uid-a", "source": "ContainerLogV2"}
    query = json.loads(requests[0].content)["query"]
    assert "AppTraces" in query
    assert "AppExceptions" in query
    assert "ContainerLogV2" in query
    assert "| where pod_uid == 'pod-uid-a'" in query


@pytest.mark.asyncio
async def test_log_provider_routes_neutral_resource_to_discovered_workspace_first() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/workspaces/00000000-0000-0000-0000-000000000000/" in request.url.path:
            return httpx.Response(
                200,
                json=_table(
                    ["at", "body", "severity", "service", "resource_id", "source"],
                    [["2026-07-20T11:59:00Z", "failed", "error", "api", "", "AppTraces"]],
                ),
            )
        return httpx.Response(200, json=_table(["at"], []))

    provider = AzureLogAnalyticsRcaLogProvider(
        _provider(handler),
        workspace_resolver=_WorkspaceResolver(),
    )
    records = [
        record
        async for record in provider.query(
            LogQuery(
                expression="",
                labels={"resource_id": "resource-neutral"},
                since=_NOW - timedelta(hours=1),
                until=_NOW,
                limit=20,
            )
        )
    ]

    assert len(records) == 1
    assert "/workspaces/00000000-0000-0000-0000-000000000000/query" in str(requests[0].url)
    assert "/workspaces/workspace-test/query" in str(requests[1].url)
    query = json.loads(requests[0].content)["query"]
    assert "Properties['cloud.resource_id']" in query
    assert "Microsoft.Web/sites/app-example" in query
    assert "resource-neutral" not in query


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


@pytest.mark.asyncio
async def test_multi_workspace_results_are_globally_ordered_and_limited() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        workspace = request.url.path.split("/workspaces/", 1)[1].split("/", 1)[0]
        timestamps = {
            "a-workspace": "2026-07-20T11:59:30Z",
            "b-workspace": "2026-07-20T11:58:30Z",
            "workspace-test": "2026-07-20T11:57:30Z",
        }
        return httpx.Response(
            200,
            json=_table(
                ["at", "body", "severity", "service", "resource_id", "source"],
                [[timestamps[workspace], workspace, "error", "api", "", "AppTraces"]],
            ),
        )

    provider = AzureLogAnalyticsRcaLogProvider(
        _provider(handler),
        workspace_resolver=_StaticWorkspaceResolver(("a-workspace", "b-workspace")),
    )
    records = [
        record
        async for record in provider.query(
            LogQuery(
                expression="",
                labels={"resource_id": "resource-neutral"},
                since=_NOW - timedelta(hours=1),
                until=_NOW,
                limit=2,
            )
        )
    ]
    assert [record.body for record in records] == ["workspace-test", "b-workspace"]


@pytest.mark.asyncio
async def test_case_equivalent_fallback_workspace_is_queried_once() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_table(["at"], []))

    provider = AzureLogAnalyticsRcaLogProvider(
        _provider(handler),
        workspace_resolver=_StaticWorkspaceResolver(("WORKSPACE-TEST",)),
    )
    assert [
        record
        async for record in provider.query(
            LogQuery(
                expression="",
                labels={"resource_id": "resource-neutral"},
                since=_NOW - timedelta(hours=1),
                until=_NOW,
            )
        )
    ] == []
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_one_workspace_failure_discards_partial_multi_workspace_rows() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "/workspaces/b-workspace/" in request.url.path:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=_table(
                ["at", "body", "severity", "service", "resource_id", "source"],
                [["2026-07-20T11:59:00Z", "failed", "error", "api", "", "AppTraces"]],
            ),
        )

    provider = AzureLogAnalyticsRcaLogProvider(
        _provider(handler),
        workspace_resolver=_StaticWorkspaceResolver(("a-workspace", "b-workspace")),
    )
    with pytest.raises(LogQueryProviderError, match="RCA log query failed"):
        _ = [
            record
            async for record in provider.query(
                LogQuery(
                    expression="",
                    labels={"resource_id": "resource-neutral"},
                    since=_NOW - timedelta(hours=1),
                    until=_NOW,
                )
            )
        ]


@pytest.mark.asyncio
async def test_kql_filter_limit_applies_after_quote_escaping() -> None:
    provider = AzureLogAnalyticsRcaLogProvider(
        _provider(lambda _request: pytest.fail("unexpected query"))
    )
    with pytest.raises(LogQueryProviderError, match="RCA log query failed"):
        _ = [
            record
            async for record in provider.query(
                LogQuery(
                    expression="'" * 1_001,
                    since=_NOW - timedelta(hours=1),
                    until=_NOW,
                )
            )
        ]
