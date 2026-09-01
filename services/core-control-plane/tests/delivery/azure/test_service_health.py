"""Bounded Azure Service Health reader tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from fdai.delivery.azure.service_health import (
    AzureServiceHealthConfig,
    AzureServiceHealthReader,
)
from fdai.shared.providers.workload_identity import IdentityToken

SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
OTHER_SUBSCRIPTION_ID = SUBSCRIPTION_ID.replace("0", "1")
NOW = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)
DOTNET_EPOCH = datetime(1, 1, 1, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(minutes=5),
            audience=audience,
        )


def _payload(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "data": rows,
        "count": len(rows),
        "totalRecords": len(rows),
        "resultTruncated": False,
    }


def _dotnet_ticks(value: datetime) -> str:
    delta = value - DOTNET_EPOCH
    return str(delta.days * 864_000_000_000 + delta.seconds * 10_000_000 + delta.microseconds * 10)


async def test_reader_correlates_active_event_to_exact_subscription_impact() -> None:
    requests: list[httpx.Request] = []
    responses = iter(
        (
            httpx.Response(
                200,
                json=_payload(
                    [
                        {
                            "eventName": "event-a",
                            "trackingId": "tracking-a",
                            "eventType": "ServiceIssue",
                            "status": "Active",
                            "level": "Warning",
                            "title": "Regional connectivity issue",
                            "impactStartTime": "2026-08-21T17:50:00Z",
                        }
                    ]
                ),
            ),
            httpx.Response(
                200,
                json=_payload(
                    [
                        {
                            "eventTrackingId": "tracking-a",
                            "targetResourceId": (
                                f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
                                "providers/Microsoft.App/containerApps/service-a"
                            ),
                            "resourceName": "service-a",
                            "resourceGroup": "example-rg",
                            "targetResourceType": "microsoft.app/containerapps",
                            "targetRegion": "example-region",
                            "status": "Active",
                        }
                    ]
                ),
            ),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert len(requests) == 2
    event_query = json.loads(requests[0].content)
    impact_query = json.loads(requests[1].content)
    assert event_query["subscriptions"] == [SUBSCRIPTION_ID]
    assert "ServiceHealthResources" in event_query["query"]
    assert "tostring(properties['Status']) =~ 'Active'" in event_query["query"]
    assert "properties." not in event_query["query"]
    assert "properties." not in impact_query["query"]
    assert "tracking-a" in impact_query["query"]
    assert result.complete is True
    assert result.limitation is None
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.event_type == "service_issue"
    assert observation.resource_name == "service-a"
    assert observation.impacted_resource_count == 1
    assert observation.event_evidence_ref.startswith("azure-service-health:")
    assert observation.impact_evidence_ref is not None


async def test_reader_accepts_resource_graph_dotnet_tick_timestamp() -> None:
    impact_start = NOW - timedelta(minutes=10)
    responses = iter(
        (
            httpx.Response(
                200,
                json=_payload(
                    [
                        {
                            "eventName": "event-a",
                            "trackingId": "tracking-a",
                            "eventType": "HealthAdvisory",
                            "status": "Active",
                            "title": "Health advisory",
                            "impactStartTime": _dotnet_ticks(impact_start),
                        }
                    ]
                ),
            ),
            httpx.Response(200, json=_payload([])),
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert result.complete is True
    assert result.limitation is None
    assert result.observations[0].impact_start_at == impact_start


async def test_reader_excludes_scheduled_future_maintenance_without_losing_completeness() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_payload(
                [
                    {
                        "eventName": "event-a",
                        "trackingId": "tracking-a",
                        "eventType": "PlannedMaintenance",
                        "status": "Active",
                        "title": "Planned maintenance",
                        "impactStartTime": _dotnet_ticks(NOW + timedelta(days=1)),
                    }
                ]
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert len(requests) == 1
    assert result.complete is True
    assert result.limitation is None
    assert result.observations == ()


async def test_reader_verified_zero_skips_impact_query() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert len(requests) == 1
    assert result.complete is True
    assert result.observations == ()
    assert result.limitation is None


async def test_reader_preserves_event_when_impact_source_is_unavailable() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                json=_payload(
                    [
                        {
                            "eventName": "event-a",
                            "trackingId": "tracking-a",
                            "eventType": "PlannedMaintenance",
                            "status": "Active",
                            "level": "Informational",
                            "title": "Planned maintenance",
                            "impactStartTime": "2026-08-21T17:50:00Z",
                        }
                    ]
                ),
            ),
            httpx.Response(403),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert result.complete is False
    assert result.limitation == "impact_source_unavailable"
    assert len(result.observations) == 1
    assert result.observations[0].event_type == "planned_maintenance"
    assert result.observations[0].impacted_resource_count is None
    assert result.observations[0].resource_name is None


async def test_reader_rejects_impacted_resource_from_another_subscription() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                json=_payload(
                    [
                        {
                            "eventName": "event-a",
                            "trackingId": "tracking-a",
                            "eventType": "HealthAdvisory",
                            "status": "Active",
                            "title": "Health advisory",
                            "impactStartTime": "2026-08-21T17:50:00Z",
                        }
                    ]
                ),
            ),
            httpx.Response(
                200,
                json=_payload(
                    [
                        {
                            "eventTrackingId": "tracking-a",
                            "targetResourceId": (
                                f"/subscriptions/{OTHER_SUBSCRIPTION_ID}/"
                                "resourceGroups/example-rg/providers/Example/type/item"
                            ),
                            "resourceName": "other-resource",
                        }
                    ]
                ),
            ),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert result.complete is False
    assert result.limitation == "provider_scope_mismatch"
    assert len(result.observations) == 1
    assert result.observations[0].resource_name is None


async def test_reader_converts_event_query_failure_to_typed_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403))
    ) as client:
        reader = AzureServiceHealthReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureServiceHealthConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_active()

    assert result.complete is False
    assert result.observations == ()
    assert result.limitation == "source_unavailable"
