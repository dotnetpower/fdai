from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.deployment_history import (
    AzureActivityDeploymentHistoryProvider,
    AzureDeploymentHistoryConfig,
    AzureResolvedResourceIdentity,
)
from fdai.shared.providers.observation import DeploymentHistoryError
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

AT = datetime(2026, 9, 5, 12, tzinfo=UTC)
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
RESOURCE_REF = "scope-example/resource-group/rg-example/providers/example"
PROVIDER_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-example/"
    "providers/Microsoft.ContainerRegistry/registries/example"
)
AUDIENCE = "https://management.azure.com/.default"


class StaticIdentityResolver:
    def __init__(self, value: AzureResolvedResourceIdentity | None) -> None:
        self.value = value
        self.requests: list[str] = []
        self.at: datetime | None = None

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime | None = None,
    ) -> AzureResolvedResourceIdentity | None:
        self.requests.append(resource_ref)
        self.at = at
        return self.value


def _activity(
    *,
    event_id: str = "event-1",
    operation: str = "Microsoft.ContainerRegistry/registries/write",
    status: str = "Succeeded",
    category: str = "Administrative",
    resource_id: str = PROVIDER_ID,
    timestamp: datetime = AT - timedelta(minutes=5),
    caller: str | None = "operator@example.com",
) -> dict[str, object]:
    return {
        "eventDataId": event_id,
        "eventTimestamp": timestamp.isoformat(),
        "operationName": {"value": operation},
        "status": {"value": status},
        "category": {"value": category},
        "resourceId": resource_id,
        "caller": caller,
    }


def _provider(
    handler: httpx.MockTransport,
    *,
    resolver: StaticIdentityResolver | None = None,
    config: AzureDeploymentHistoryConfig | None = None,
) -> tuple[AzureActivityDeploymentHistoryProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler)
    return (
        AzureActivityDeploymentHistoryProvider(
            identity=StaticWorkloadIdentity(audience=AUDIENCE),
            resource_identities=resolver
            or StaticIdentityResolver(
                AzureResolvedResourceIdentity(
                    provider_resource_id=PROVIDER_ID,
                    inventory_generation="inventory-generation-1",
                )
            ),
            http_client=client,
            config=config,
            clock=lambda: AT,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_returns_only_successful_exact_scope_mutations_with_private_author() -> None:
    captured: list[httpx.Request] = []
    resolver = StaticIdentityResolver(
        AzureResolvedResourceIdentity(
            provider_resource_id=PROVIDER_ID,
            inventory_generation="inventory-generation-1",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    _activity(),
                    _activity(
                        event_id="read-1",
                        operation="Microsoft.ContainerRegistry/registries/read",
                    ),
                    _activity(event_id="failed-1", status="Failed"),
                ]
            },
        )

    provider, client = _provider(httpx.MockTransport(handler), resolver=resolver)
    try:
        result = await provider.query_deployments(window="P1D", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()

    assert len(result.records) == 1
    record = result.records[0]
    assert record.deployment_ref == "azure-activity:event-1"
    assert record.resource_refs == (RESOURCE_REF,)
    assert record.author.startswith("principal:sha256:")
    assert "operator@example.com" not in record.author
    assert record.metadata["cause_domain"] == "infrastructure"
    assert record.metadata["inventory_generation"] == "inventory-generation-1"
    request = captured[0]
    assert request.url.host == "management.azure.com"
    assert PROVIDER_ID in request.url.params["$filter"]
    assert resolver.at is None


@pytest.mark.asyncio
async def test_replay_uses_explicit_incident_cutoff_instead_of_processing_time() -> None:
    cutoff = AT - timedelta(hours=2)
    captured: list[httpx.Request] = []
    resolver = StaticIdentityResolver(
        AzureResolvedResourceIdentity(
            provider_resource_id=PROVIDER_ID,
            inventory_generation="inventory-generation-at-cutoff",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    _activity(
                        timestamp=cutoff - timedelta(minutes=5),
                    )
                ]
            },
        )

    provider, client = _provider(httpx.MockTransport(handler), resolver=resolver)
    try:
        result = await provider.query_deployments_until(
            window="PT1H",
            resource_ref=RESOURCE_REF,
            until=cutoff,
        )
    finally:
        await client.aclose()

    assert len(result.records) == 1
    assert resolver.at == cutoff
    filter_value = captured[0].url.params["$filter"]
    assert "2026-09-05T10:00:00Z" in filter_value
    assert "2026-09-05T12:00:00Z" not in filter_value


@pytest.mark.asyncio
async def test_follows_only_same_scope_continuation_and_orders_records() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "value": [_activity(event_id="event-2", timestamp=AT - timedelta(minutes=1))],
                    "nextLink": (
                        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/"
                        "providers/Microsoft.Insights/eventtypes/management/values"
                        "?api-version=2015-04-01&$skiptoken=next"
                    ),
                },
            )
        return httpx.Response(
            200,
            json={"value": [_activity(event_id="event-1", timestamp=AT - timedelta(minutes=2))]},
        )

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        result = await provider.query_deployments(window="PT1H", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()

    assert calls == 2
    assert [item.deployment_ref for item in result.records] == [
        "azure-activity:event-1",
        "azure-activity:event-2",
    ]


@pytest.mark.asyncio
async def test_rejects_continuation_that_changes_original_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [],
                "nextLink": (
                    f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}/"
                    "providers/Microsoft.Insights/eventtypes/management/values"
                    "?api-version=2015-04-01&$filter=resourceUri%20eq%20'other'"
                    "&$skiptoken=next"
                ),
            },
        )

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(DeploymentHistoryError, match="changed its resource filter"):
            await provider.query_deployments(window="P1D", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_rejects_scope_escape_and_incomplete_provider_evidence() -> None:
    wrong_resource = PROVIDER_ID.replace("/example", "/other")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [_activity(resource_id=wrong_resource)]})

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(DeploymentHistoryError, match="out-of-scope"):
            await provider.query_deployments(window="P1D", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()

    missing, client = _provider(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []})),
        resolver=StaticIdentityResolver(None),
    )
    try:
        with pytest.raises(DeploymentHistoryError, match="identity is unavailable"):
            await missing.query_deployments(window="P1D", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_rejects_invalid_window_unauthorized_and_record_overflow() -> None:
    unauthorized, client = _provider(
        httpx.MockTransport(lambda request: httpx.Response(403, json={}))
    )
    try:
        with pytest.raises(DeploymentHistoryError, match="HTTP 403"):
            await unauthorized.query_deployments(window="P1D", resource_ref=RESOURCE_REF)
        with pytest.raises(DeploymentHistoryError, match="ISO 8601"):
            await unauthorized.query_deployments(window="yesterday", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()

    overflow, client = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=json.dumps(
                    {"value": [_activity(event_id="one"), _activity(event_id="two")]}
                ),
            )
        ),
        config=AzureDeploymentHistoryConfig(maximum_records=1),
    )
    try:
        with pytest.raises(DeploymentHistoryError, match="record bound"):
            await overflow.query_deployments(window="P1D", resource_ref=RESOURCE_REF)
    finally:
        await client.aclose()


def test_configuration_rejects_unapproved_endpoint_and_unbounded_responses() -> None:
    government = AzureDeploymentHistoryConfig(
        endpoint="https://management.usgovcloudapi.net",
        audience="https://management.usgovcloudapi.net/.default",
    )
    assert government.endpoint == "https://management.usgovcloudapi.net"
    with pytest.raises(ValueError, match="match the Azure endpoint cloud"):
        AzureDeploymentHistoryConfig(
            endpoint="https://management.usgovcloudapi.net",
            audience="https://management.azure.com/.default",
        )
    with pytest.raises(ValueError, match="approved Azure origin"):
        AzureDeploymentHistoryConfig(endpoint="https://example.com")
    with pytest.raises(ValueError, match="per-page byte"):
        AzureDeploymentHistoryConfig(maximum_response_bytes=4 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="total byte"):
        AzureDeploymentHistoryConfig(
            maximum_response_bytes=100,
            maximum_total_response_bytes=16 * 1024 * 1024 + 1,
        )
