from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx

from fdai.delivery.azure.subscription_health import (
    AzureSubscriptionHealthConfig,
    AzureSubscriptionHealthProvider,
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
                "/subscriptions/example/resourceGroups/rg-example/providers/"
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
                "/subscriptions/example/resourceGroups/rg-example/providers/"
                "Microsoft.KeyVault/vaults/vault-app"
            ),
            "name": "vault-app",
            "type": "microsoft.keyvault/vaults",
            "resourceGroup": "rg-example",
            "location": "example-region",
            "provisioningState": "Succeeded",
        },
    ]


def _handler(*, metric_status: int = 200):
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
