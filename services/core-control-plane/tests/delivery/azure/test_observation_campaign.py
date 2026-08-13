"""Focused Azure observation probe boundary tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.observation_campaign import (
    AzureActivityLogObservationProbe,
    AzureCostObservationProbe,
    AzureLogAnalyticsObservationProbe,
    AzureObservationConfig,
    AzureResourceGraphObservation,
    AzureResourceGraphObservationProbe,
    PromotedInventoryObservationProbe,
    _subscription_cursor_key,
)
from fdai.delivery.observation_campaign import ObservationCoverage, ObservationSourceSpec
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai_service_contracts import ObservationDomain


def _spec(source_id: str, domain: ObservationDomain, owner: str) -> ObservationSourceSpec:
    return ObservationSourceSpec(
        source_id=source_id,
        domain=domain,
        owner_agent=owner,  # type: ignore[arg-type]
        interval_seconds=60,
        lookback_seconds=300,
        timeout_seconds=2,
        max_targets=4,
        max_results=10,
        max_output_bytes=64_000,
    )


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="token",
    )


async def test_resource_graph_probe_uses_reviewed_query_and_reports_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer token"
        assert "healthresources" in request.content.decode().lower()
        assert "summarize evidence_count=count()" in request.content.decode()
        return httpx.Response(200, json={"data": [{"evidence_count": 1}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureResourceGraphObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            query=AzureResourceGraphObservation.RESOURCE_HEALTH,
            identity=_identity(),
            http_client=client,
        ).collect(
            _spec("resource-health", ObservationDomain.RESOURCE_HEALTH, "Heimdall"),
            cursor=None,
        )

    assert result.coverage is ObservationCoverage.READY
    assert result.evidence_count == 1


async def test_resource_graph_probe_enforces_target_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["subscriptions"] == ["sub-1"]
        return httpx.Response(200, json={"data": [{"evidence_count": 0}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureResourceGraphObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub-1", "sub-2")),
            query=AzureResourceGraphObservation.RESOURCE_HEALTH,
            identity=_identity(),
            http_client=client,
        ).collect(
            ObservationSourceSpec(
                source_id="resource-health",
                domain=ObservationDomain.RESOURCE_HEALTH,
                owner_agent="Heimdall",
                interval_seconds=60,
                lookback_seconds=300,
                timeout_seconds=2,
                max_targets=1,
                max_results=10,
                max_output_bytes=64_000,
            ),
            cursor=None,
        )

    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.reason_codes == ("target_limit",)


async def test_service_health_probe_counts_active_events_without_properties() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        assert "properties.Status =~ 'Active'" in query
        assert "project id" not in query
        return httpx.Response(200, json={"data": [{"evidence_count": 17}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureResourceGraphObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            query=AzureResourceGraphObservation.SERVICE_HEALTH,
            identity=_identity(),
            http_client=client,
        ).collect(
            _spec("service-health", ObservationDomain.SERVICE_HEALTH, "Heimdall"),
            cursor=None,
        )

    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.evidence_count == 10
    assert result.reason_codes == ("result_limit",)


async def test_activity_log_probe_normalizes_permission_denial() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(403, json={}))
    ) as client:
        probe = AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
        )
        try:
            await probe.collect(
                _spec("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
                cursor=None,
            )
        except PermissionError:
            denied = True
        else:
            denied = False

    assert denied


async def test_activity_log_follows_pages_before_advancing_anonymous_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [{"eventTimestamp": "2026-08-14T00:00:01Z"}],
                    "nextLink": (
                        "https://management.azure.com/subscriptions/sub/providers/"
                        "microsoft.insights/eventtypes/management/values?token=opaque"
                    ),
                },
            )
        return httpx.Response(
            200,
            json={"value": [{"eventTimestamp": "2026-08-14T00:00:02Z"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
            clock=lambda: datetime(2026, 8, 14, tzinfo=UTC),
        ).collect(
            _spec("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
            cursor=None,
        )

    assert len(requests) == 2
    assert result.coverage is ObservationCoverage.READY
    assert result.evidence_count == 2
    cursor = json.loads(result.cursor or "")
    assert list(cursor["subscriptions"].values()) == ["2026-08-14T00:00:02Z"]
    assert list(cursor["subscriptions"]) != ["sub"]
    assert all(key.startswith("sha256:") for key in cursor["subscriptions"])


async def test_activity_log_keeps_prior_cursor_when_page_limit_leaves_unread_data() -> None:
    prior_cursor = "2026-08-13T00:00:00+00:00"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {"eventTimestamp": "2026-08-14T00:00:01Z"},
                    {"eventTimestamp": "2026-08-14T00:00:02Z"},
                ],
                "nextLink": (
                    "https://management.azure.com/subscriptions/sub/providers/"
                    "microsoft.insights/eventtypes/management/values?token=opaque"
                ),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
        ).collect(
            ObservationSourceSpec(
                source_id="activity-log",
                domain=ObservationDomain.ACTIVITY_LOG,
                owner_agent="Huginn",
                interval_seconds=60,
                lookback_seconds=300,
                timeout_seconds=2,
                max_targets=4,
                max_results=1,
                max_output_bytes=64_000,
            ),
            cursor=prior_cursor,
        )

    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.evidence_count == 1
    assert result.cursor is None
    assert result.reason_codes == ("result_limit",)


async def test_activity_log_result_limit_does_not_starve_later_subscription() -> None:
    requested_subscriptions: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        subscription = request.url.path.split("/")[2]
        requested_subscriptions.append(subscription)
        return httpx.Response(
            200,
            json={
                "value": [
                    {"eventTimestamp": "2026-08-14T00:00:01Z"},
                    {"eventTimestamp": "2026-08-14T00:00:02Z"},
                ],
                "nextLink": (
                    f"https://management.azure.com/subscriptions/{subscription}/providers/"
                    "microsoft.insights/eventtypes/management/values?token=opaque"
                ),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub-1", "sub-2")),
            identity=_identity(),
            http_client=client,
        ).collect(
            ObservationSourceSpec(
                source_id="activity-log",
                domain=ObservationDomain.ACTIVITY_LOG,
                owner_agent="Huginn",
                interval_seconds=60,
                lookback_seconds=300,
                timeout_seconds=2,
                max_targets=2,
                max_results=2,
                max_output_bytes=64_000,
            ),
            cursor=None,
        )

    assert requested_subscriptions == ["sub-1", "sub-2"]
    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.evidence_count == 2
    assert result.reason_codes == ("result_limit",)


async def test_activity_log_rejects_cross_subscription_next_link() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [],
                "nextLink": (
                    "https://management.azure.com/subscriptions/other/providers/"
                    "microsoft.insights/eventtypes/management/values?token=opaque"
                ),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
        )
        try:
            await probe.collect(
                _spec("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
                cursor=None,
            )
        except RuntimeError as exc:
            message = str(exc)
        else:
            message = ""

    assert "within its subscription" in message


async def test_activity_log_rejects_malformed_legacy_cursor() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"value": []}))
    ) as client:
        probe = AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
        )
        try:
            await probe.collect(
                _spec("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
                cursor="not-a-timestamp",
            )
        except RuntimeError as exc:
            message = str(exc)
        else:
            message = ""

    assert "cursor failed validation" in message


async def test_activity_log_prunes_retired_cursor_and_advances_empty_source() -> None:
    current_key = _subscription_cursor_key("sub")
    retired_key = _subscription_cursor_key("retired")
    prior = json.dumps(
        {
            "subscriptions": {
                current_key: "2026-08-13T00:00:00Z",
                retired_key: "2026-08-12T00:00:00Z",
            },
            "version": 1,
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"value": []}))
    ) as client:
        result = await AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
            clock=lambda: datetime(2026, 8, 14, tzinfo=UTC),
        ).collect(
            _spec("activity-log", ObservationDomain.ACTIVITY_LOG, "Huginn"),
            cursor=prior,
        )

    cursor = json.loads(result.cursor or "")
    assert cursor["subscriptions"] == {current_key: "2026-08-14T00:00:00+00:00"}


async def test_activity_log_many_subscriptions_use_conservative_bounded_cursor() -> None:
    subscriptions = tuple(f"sub-{index}" for index in range(50))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"value": []}))
    ) as client:
        result = await AzureActivityLogObservationProbe(
            config=AzureObservationConfig(subscription_ids=subscriptions),
            identity=_identity(),
            http_client=client,
            clock=lambda: datetime(2026, 8, 14, tzinfo=UTC),
        ).collect(
            ObservationSourceSpec(
                source_id="activity-log",
                domain=ObservationDomain.ACTIVITY_LOG,
                owner_agent="Huginn",
                interval_seconds=60,
                lookback_seconds=300,
                timeout_seconds=2,
                max_targets=50,
                max_results=100,
                max_output_bytes=64_000,
            ),
            cursor=None,
        )

    assert result.coverage is ObservationCoverage.READY
    assert result.cursor == "2026-08-14T00:00:00+00:00"
    assert len(result.cursor) <= 4096


async def test_cost_probe_discards_values_and_reports_row_count() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"properties": {"rows": [[123.45, "redacted"]]}},
            )
        )
    ) as client:
        result = await AzureCostObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
        ).collect(
            _spec("cost", ObservationDomain.COST, "Njord"),
            cursor=None,
        )

    assert result.evidence_count == 1


async def test_cost_probe_reports_result_limit_as_partial() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"properties": {"rows": [[1], [2], [3]]}},
            )
        )
    ) as client:
        result = await AzureCostObservationProbe(
            config=AzureObservationConfig(subscription_ids=("sub",)),
            identity=_identity(),
            http_client=client,
        ).collect(
            ObservationSourceSpec(
                source_id="cost",
                domain=ObservationDomain.COST,
                owner_agent="Njord",
                interval_seconds=60,
                lookback_seconds=300,
                timeout_seconds=2,
                max_targets=4,
                max_results=2,
                max_output_bytes=64_000,
            ),
            cursor=None,
        )

    assert result.coverage is ObservationCoverage.PARTIAL
    assert result.evidence_count == 2
    assert result.reason_codes == ("result_limit",)


async def test_log_analytics_probe_uses_server_owned_template() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "AzureActivity" in body and "AzureDiagnostics" in body
        return httpx.Response(
            200,
            json={
                "tables": [
                    {
                        "columns": [{"name": "Count", "type": "long"}],
                        "rows": [[1]],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureLogAnalyticsQueryProvider(
            config=AzureLogAnalyticsQueryConfig(workspace_id="workspace"),
            identity=StaticWorkloadIdentity(
                audience="https://api.loganalytics.io/.default",
                token="token",
            ),
            http_client=client,
        )
        result = await AzureLogAnalyticsObservationProbe(provider, source_id="logs").collect(
            _spec("logs", ObservationDomain.LOGS, "Heimdall"),
            cursor=None,
        )

    assert result.coverage is ObservationCoverage.READY
    assert result.evidence_count == 1


async def test_promoted_inventory_probe_reports_stale_without_raw_resources() -> None:
    async def summary(_limit: int):
        return {
            "source": "azure-resource-graph",
            "freshness": "stale",
            "resource_count": 1,
            "link_count": 0,
            "truncated": False,
        }

    result = await PromotedInventoryObservationProbe(summary).collect(
        _spec("inventory", ObservationDomain.INVENTORY, "Huginn"),
        cursor=None,
    )

    assert result.coverage is ObservationCoverage.STALE
    assert result.reason_codes == ("source_stale",)
