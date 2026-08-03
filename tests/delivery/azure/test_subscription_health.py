from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from fdai.delivery.azure.subscription_health import (
    AzureSubscriptionHealthConfig,
    AzureSubscriptionHealthProvider,
    AzureSubscriptionHealthScope,
    MetricProbeSpec,
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _Identity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="fake",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


class _ConcurrentTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.release = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if body["query"].startswith("HealthResources"):
                return httpx.Response(200, json={"data": []})
            resources = [
                {
                    **_resource_rows()[0],
                    "id": f"{_resource_rows()[0]['id']}-{index}",
                    "name": f"vm-{index}",
                }
                for index in range(5)
            ]
            return httpx.Response(200, json={"data": resources})
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active == 2:
            self.release.set()
        try:
            await asyncio.wait_for(self.release.wait(), timeout=0.5)
            await asyncio.sleep(0)
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"timeseries": [{"data": [{"maximum": 10.0}]}]},
                    ]
                },
            )
        finally:
            self.active -= 1


def _resource_rows() -> list[dict[str, object]]:
    return [
        {
            "id": (
                "/subscriptions/subscription-example/resourceGroups/rg-example/providers/"
                "Microsoft.Compute/virtualMachines/vm-app"
            ),
            "name": "vm-app",
            "type": "microsoft.compute/virtualmachines",
            "resourceGroup": "rg-example",
            "location": "example-region",
            "provisioningState": "Succeeded",
        },
        {
            "id": (
                "/subscriptions/subscription-example/resourceGroups/rg-example/providers/"
                "Microsoft.KeyVault/vaults/vault-app"
            ),
            "name": "vault-app",
            "type": "microsoft.keyvault/vaults",
            "resourceGroup": "rg-example",
            "location": "example-region",
            "provisioningState": "Succeeded",
        },
    ]


def _handler(*, metric_status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            query = body["query"]
            if query.startswith("HealthResources"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "targetResourceId": _resource_rows()[0]["id"],
                                "resourceName": "vm-app",
                                "availabilityState": "Degraded",
                                "reasonType": "PlatformInitiated",
                                "occurredTime": "2026-07-22T04:55:00Z",
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"data": _resource_rows()})
        if metric_status >= 400:
            return httpx.Response(metric_status, json={"error": "throttled"})
        timespan = request.url.params["timespan"]
        assert timespan.count("Z") == 2
        assert "+" not in timespan
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "timeseries": [
                            {
                                "data": [
                                    {
                                        "timeStamp": "2026-07-22T04:55:00Z",
                                        "maximum": 95.0,
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        )

    return handle


async def _run(metric_status: int = 200) -> dict[str, object]:
    transport = httpx.MockTransport(_handler(metric_status=metric_status))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        return await provider(3_600)


async def test_subscription_health_combines_health_and_metric_findings() -> None:
    result = await _run()

    assert result["status"] == "partial"
    assert result["resource_count"] == 2
    assert result["metric_checked"] == 1
    assert result["unsupported_metric_resources"] == 1
    findings = result["findings"]
    assert isinstance(findings, list)
    assert {item["kind"] for item in findings} == {"resource_health", "metric"}
    assert next(item for item in findings if item["kind"] == "metric")["value"] == 95.0


async def test_subscription_health_metric_failure_is_partial_not_healthy() -> None:
    result = await _run(metric_status=429)

    assert result["status"] == "partial"
    assert result["metric_checked"] == 0
    assert result["metric_unavailable"] == 1
    assert result["findings"]


async def test_platform_health_merges_customer_annotation_without_metrics() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        query = json.loads(request.content)["query"]
        requests.append(query)
        if "resourceannotations" in query:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _resource_rows()[0]["id"],
                            "annotationName": "Stopped by user",
                            "context": "Customer Initiated",
                            "reason": "Stopped by user",
                            "occurredTime": "2026-07-22T04:56:00Z",
                        }
                    ]
                },
            )
        if query.startswith("HealthResources"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _resource_rows()[0]["id"],
                            "resourceName": "vm-app",
                            "availabilityState": "Unavailable",
                            "reasonType": "",
                            "occurredTime": "2026-07-22T04:55:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"data": _resource_rows()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_health(3_600, include_metrics=False)

    finding = next(item for item in result["findings"] if item["kind"] == "resource_health")
    assert finding["reason"] == "Customer Initiated"
    assert result["metrics_requested"] is False
    assert result["metric_checked"] == 0
    assert result["resource_annotation_unavailable"] == 0
    assert any("resourceannotations" in query for query in requests)


async def test_platform_health_correlates_active_service_health_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        query = json.loads(request.content)["query"]
        if query.startswith("ServiceHealthResources") and "impactedresources" in query:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "eventTrackingId": "issue-1",
                            "resourceName": "vm-app",
                            "resourceGroup": "rg-example",
                            "targetResourceType": "Microsoft.Compute/virtualMachines",
                            "targetRegion": "example-region",
                            "status": "Active",
                        },
                        {
                            "eventTrackingId": "maintenance-1",
                            "resourceName": "database-app",
                            "resourceGroup": "rg-example",
                            "targetResourceType": "Microsoft.DBforPostgreSQL/flexibleServers",
                            "targetRegion": "example-region",
                            "status": "Active",
                        },
                    ]
                },
            )
        if query.startswith("ServiceHealthResources"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "eventName": "issue-1",
                            "trackingId": "issue-1",
                            "eventType": "ServiceIssue",
                            "status": "Active",
                            "level": "Warning",
                            "title": "Example compute issue",
                            "impactStartTime": "2026-07-22T04:50:00Z",
                        },
                        {
                            "eventName": "maintenance-1",
                            "trackingId": "maintenance-1",
                            "eventType": "PlannedMaintenance",
                            "status": "Active",
                            "level": "Informational",
                            "title": "Example database maintenance",
                            "impactStartTime": "2026-07-22T05:00:00Z",
                        },
                    ]
                },
            )
        if "resourceannotations" in query:
            return httpx.Response(200, json={"data": []})
        if query.startswith("HealthResources"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"data": _resource_rows()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
                scope=AzureSubscriptionHealthScope.SUBSCRIPTION,
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_health(
            3_600,
            include_metrics=False,
            include_service_health=True,
        )

    assert result["status"] == "matched"
    assert result["source"] == "azure-resource-graph+resource-health+service-health"
    assert result["service_health_unavailable"] == 0
    assert result["active_service_issue_count"] == 1
    assert result["active_service_issue_resource_count"] == 1
    assert result["active_planned_maintenance_count"] == 1
    assert result["active_planned_maintenance_resource_count"] == 1
    assert result["service_health_events"] == [
        {
            "event_type": "ServiceIssue",
            "status": "Active",
            "level": "Warning",
            "title": "Example compute issue",
            "impact_start_time": "2026-07-22T04:50:00Z",
            "impacted_resource_count": 1,
            "impacted_resources": [
                {
                    "name": "vm-app",
                    "resource_group": "rg-example",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "region": "example-region",
                    "status": "Active",
                }
            ],
        },
        {
            "event_type": "PlannedMaintenance",
            "status": "Active",
            "level": "Informational",
            "title": "Example database maintenance",
            "impact_start_time": "2026-07-22T05:00:00Z",
            "impacted_resource_count": 1,
            "impacted_resources": [
                {
                    "name": "database-app",
                    "resource_group": "rg-example",
                    "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
                    "region": "example-region",
                    "status": "Active",
                }
            ],
        },
    ]


async def test_platform_health_service_health_failure_is_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        query = json.loads(request.content)["query"]
        if query.startswith("ServiceHealthResources"):
            return httpx.Response(503, json={"error": "unavailable"})
        if query.startswith("HealthResources"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"data": _resource_rows()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
                scope=AzureSubscriptionHealthScope.SUBSCRIPTION,
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_health(
            3_600,
            include_metrics=False,
            include_service_health=True,
        )

    assert result["status"] == "partial"
    assert result["resource_count"] == 2
    assert result["service_health_unavailable"] == 1
    assert result["service_health_events"] == []


async def test_resource_health_history_filters_window_and_orders_events() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        query = json.loads(request.content)["query"]
        queries.append(query)
        if "resourceannotations" in query:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _resource_rows()[0]["id"],
                            "annotationName": "Stopped by user",
                            "context": "Customer Initiated",
                            "reason": "Stopped by user",
                            "occurredTime": "2026-07-22T03:30:00Z",
                        }
                    ]
                },
            )
        if query.startswith("HealthResources"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _resource_rows()[0]["id"],
                            "resourceName": "vm-app",
                            "availabilityState": "Available",
                            "reasonType": "Platform Initiated",
                            "title": "Availability restored",
                            "occurredTime": "2026-07-22T04:30:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"data": _resource_rows()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_health_history(86_400)

    assert result["status"] == "matched"
    assert result["source"] == "azure-resource-graph+resource-health-history"
    assert result["metrics_requested"] is False
    assert [event["kind"] for event in result["health_history_events"]] == [
        "resource_annotation",
        "availability_status",
    ]
    assert [event["classification"] for event in result["health_history_events"]] == [
        "customer-initiated",
        "platform-initiated",
    ]
    history_queries = [query for query in queries if query.startswith("HealthResources")]
    assert len(history_queries) == 2
    assert all("ago(86400s)" in query for query in history_queries)
    assert all("order by occurredTime asc" in query for query in history_queries)
    assert all("properties.title" not in query for query in history_queries)


async def test_platform_health_annotation_failure_is_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        query = json.loads(request.content)["query"]
        if "resourceannotations" in query:
            return httpx.Response(503, json={"error": "unavailable"})
        if query.startswith("HealthResources"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _resource_rows()[0]["id"],
                            "resourceName": "vm-app",
                            "availabilityState": "Unknown",
                            "reasonType": "",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"data": _resource_rows()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_health(3_600, include_metrics=False)

    assert result["status"] == "partial"
    assert result["resource_annotation_unavailable"] == 1
    finding = next(item for item in result["findings"] if item["kind"] == "resource_health")
    assert finding["reason"] == "unknown"


async def test_subscription_scope_metadata_uses_configured_subscription() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/subscriptions/subscription-example"
        assert request.url.params["api-version"] == "2022-12-01"
        assert request.headers["Authorization"] == "Bearer fake"
        return httpx.Response(
            200,
            json={
                "subscriptionId": "subscription-example",
                "displayName": "Example Development",
                "state": "Enabled",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.describe_scope()

    assert result["status"] == "matched"
    assert result["source"] == "azure-resource-manager"
    assert result["display_name"] == "Example Development"
    assert result["subscription_id"] == "subscription-example"
    assert result["state"] == "Enabled"


async def test_subscription_health_uses_current_resource_health_when_arg_is_empty() -> None:
    resource = _resource_rows()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if body["query"].startswith("HealthResources"):
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": [resource]})
        if request.url.path.endswith(
            "/resourceGroups/rg-example/providers/Microsoft.ResourceHealth/availabilityStatuses"
        ):
            assert request.url.params["api-version"] == "2025-05-01"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": (
                                f"{resource['id']}/providers/Microsoft.ResourceHealth/"
                                "availabilityStatuses/current"
                            ),
                            "properties": {
                                "availabilityState": "Degraded",
                                "reasonType": "Customer Initiated",
                                "title": "Stopped",
                                "occurredTime": "2026-07-22T04:55:00Z",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"value": [{"timeseries": [{"data": [{"maximum": 10.0}]}]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider(3_600)

    assert result["resource_health_unavailable"] == 0
    findings = result["findings"]
    assert isinstance(findings, list)
    assert findings == [
        {
            "kind": "resource_health",
            "resource_name": "vm-app",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "resource_group": "rg-example",
            "status": "Degraded",
            "reason": "Customer Initiated",
            "title": "Stopped",
            "observed_at": "2026-07-22T04:55:00Z",
        }
    ]


async def test_subscription_scope_includes_health_outside_configured_groups() -> None:
    outside_resource = {
        **_resource_rows()[0],
        "id": (
            "/subscriptions/subscription-example/resourceGroups/rg-other/providers/"
            "Microsoft.Compute/virtualMachines/vm-other"
        ),
        "name": "vm-other",
        "resourceGroup": "rg-other",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            query = json.loads(request.content)["query"]
            assert "rg-example" not in query
            if query.startswith("HealthResources"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "targetResourceId": outside_resource["id"],
                                "availabilityState": "Unavailable",
                                "reasonType": "PlatformInitiated",
                                "occurredTime": "2026-08-01T04:01:00Z",
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"data": [outside_resource]})
        return httpx.Response(
            200,
            json={"value": [{"timeseries": [{"data": [{"maximum": 10.0}]}]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
                scope=AzureSubscriptionHealthScope.SUBSCRIPTION,
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider(3_600)

    findings = result["findings"]
    assert isinstance(findings, list)
    assert any(
        finding["resource_name"] == "vm-other"
        and finding["resource_type"] == "Microsoft.Compute/virtualMachines"
        and finding["resource_group"] == "rg-other"
        and finding["status"] == "Unavailable"
        for finding in findings
    )


async def test_subscription_health_bounds_parallel_metric_queries() -> None:
    transport = _ConcurrentTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
                max_concurrent_queries=2,
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider(3_600)

    assert result["metric_checked"] == 5
    assert transport.max_active == 2


async def test_subscription_health_prefilters_one_provider_resource_type() -> None:
    storage = {
        "id": (
            "/subscriptions/subscription-example/resourceGroups/rg-example/providers/"
            "Microsoft.Storage/storageAccounts/storage-example"
        ),
        "name": "storage-example",
        "type": "microsoft.storage/storageaccounts",
        "resourceGroup": "rg-example",
        "location": "example-region",
        "provisioningState": "Succeeded",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            query = json.loads(request.content)["query"]
            if query.startswith("HealthResources"):
                assert "type =~ 'microsoft.resourcehealth/availabilitystatuses'" in query
                assert (
                    "tostring(properties.targetResourceType) in~ "
                    "('Microsoft.Storage/storageAccounts')" in query
                )
                assert (
                    "tostring(properties.availabilityState) in~ "
                    "('degraded', 'unavailable')" in query
                )
                return httpx.Response(200, json={"data": []})
            assert "type =~ 'Microsoft.Storage/storageAccounts'" in query
            return httpx.Response(200, json={"data": [storage]})
        raise AssertionError("typed state query must not widen to REST or metrics")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_resource_types(
            3_600,
            resource_types=("Microsoft.Storage/storageAccounts",),
            availability_states=("degraded", "unavailable"),
            include_metrics=False,
        )

    assert result["status"] == "matched"
    assert result["resource_count"] == 1
    assert result["metrics_requested"] is False
    assert result["metric_checked"] == 0
    assert result["unsupported_metric_resources"] == 0
    assert result["source"] == "azure-resource-graph+resource-health"
    assert result["truncated"] is False


async def test_subscription_health_projects_requested_resource_state() -> None:
    app = {
        "id": (
            "/subscriptions/subscription-example/resourceGroups/rg-example/providers/"
            "Microsoft.Web/sites/app-example"
        ),
        "name": "app-example",
        "type": "microsoft.web/sites",
        "resourceGroup": "rg-example",
        "location": "example-region",
        "provisioningState": "Succeeded",
        "state": "Stopped",
        "status": "",
        "resourceState": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            query = json.loads(request.content)["query"]
            if query.startswith("HealthResources"):
                return httpx.Response(200, json={"data": []})
            assert "state=tostring(properties.state)" in query
            return httpx.Response(200, json={"data": [app]})
        raise AssertionError("state-only app query must not request metrics")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_resource_types(
            3_600,
            resource_types=("Microsoft.Web/sites",),
            kind_tokens_by_resource_type={},
            availability_states=("stopped", "failed", "degraded", "unavailable"),
            include_metrics=False,
        )

    assert result["findings"] == [
        {
            "kind": "resource_state",
            "resource_name": "app-example",
            "resource_type": "microsoft.web/sites",
            "resource_group": "rg-example",
            "status": "Stopped",
        }
    ]


async def test_subscription_health_prefilters_shared_arm_type_by_kind() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            raise AssertionError("kind-filtered state query must not use REST or metrics")
        query = json.loads(request.content)["query"]
        if query.startswith("HealthResources"):
            return httpx.Response(200, json={"data": []})
        assert "type =~ 'Microsoft.Web/sites'" in query
        assert "kind has 'app'" in query
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_resource_types(
            3_600,
            resource_types=("Microsoft.Web/sites",),
            kind_tokens_by_resource_type={"Microsoft.Web/sites": ("app",)},
            availability_states=("stopped", "failed", "degraded", "unavailable"),
            include_metrics=False,
        )

    assert result["status"] == "matched"
    assert result["resource_count"] == 0


async def test_metric_comparison_queries_same_resource_before_and_after_anchor() -> None:
    metric_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metric_calls
        if request.method == "POST":
            return httpx.Response(200, json={"data": [_resource_rows()[0]]})
        metric_calls += 1
        value = 40.0 if metric_calls == 1 else 70.0
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "timeseries": [
                            {
                                "data": [
                                    {
                                        "timeStamp": "2026-07-22T04:30:00Z",
                                        "maximum": value,
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionHealthProvider(
            config=AzureSubscriptionHealthConfig(
                subscription_id="subscription-example",
                resource_groups=("rg-example",),
                metric_probes=(
                    MetricProbeSpec(
                        "microsoft.compute/virtualmachines",
                        "memory_percent",
                        "Maximum",
                        "gt",
                        90.0,
                    ),
                ),
            ),
            identity=_Identity(),
            http_client=client,
        )
        result = await provider.query_metric_comparison(
            anchor_at="2026-07-22T05:00:00Z",
            metric_family="memory",
            window_seconds=3_600,
        )

    assert metric_calls == 2
    assert result["status"] == "matched"
    assert result["metric_checked"] == 1
    comparison = result["metric_comparisons"][0]
    assert comparison["before_value"] == 40.0
    assert comparison["after_value"] == 70.0
    assert comparison["delta"] == 30.0
    assert comparison["before_points"] == 1
    assert comparison["after_points"] == 1
