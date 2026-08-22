"""Bounded Azure Resource Health history reader tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from fdai.delivery.azure.resource_event_history import (
    AzureResourceEventHistoryConfig,
    AzureResourceEventHistoryReader,
)
from fdai.shared.providers.workload_identity import IdentityToken

SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
NOW = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
RESOURCE_ID = (
    "scope-0123456789abcdef/resource-group/example-rg/providers/"
    "microsoft.app/containerapps/service-a"
)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(minutes=5),
            audience=audience,
        )


def _arm(name: str = "service-a") -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
        f"providers/microsoft.app/containerapps/{name}"
    )


async def test_history_reader_returns_chronological_health_events() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "targetResourceId": _arm(),
                        "sourceType": "microsoft.resourcehealth/resourceannotations",
                        "annotationName": "Downtime",
                        "context": "Customer Initiated",
                        "reason": "Stopped",
                        "occurredTime": "2026-08-21T16:55:00Z",
                    },
                    {
                        "targetResourceId": _arm(),
                        "sourceType": "microsoft.resourcehealth/availabilitystatuses",
                        "availabilityState": "Unavailable",
                        "reasonType": "Platform Initiated",
                        "occurredTime": "2026-08-21T16:50:00Z",
                    },
                ],
                "count": 2,
                "totalRecords": 2,
                "resultTruncated": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureResourceEventHistoryReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceEventHistoryConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_history(
            resource_ids=(RESOURCE_ID,),
            event_families=("resource_event.resource_health",),
            lookback_seconds=3600,
        )

    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert "ago(3600s)" in body["query"]
    assert result.complete is True
    assert [item.event_kind for item in result.events] == [
        "availability_status",
        "resource_annotation",
    ]
    assert [item.classification for item in result.events] == [
        "platform_initiated",
        "customer_initiated",
    ]
    assert result.events[0].evidence_ref.startswith("azure-resource-event:")


async def test_history_reader_distinguishes_verified_zero_from_unavailable() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                json={
                    "data": [],
                    "count": 0,
                    "totalRecords": 0,
                    "resultTruncated": False,
                },
            ),
            httpx.Response(403),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as client:
        reader = AzureResourceEventHistoryReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceEventHistoryConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        empty = await reader.read_history(
            resource_ids=(RESOURCE_ID,),
            event_families=("resource_event.resource_health",),
            lookback_seconds=3600,
        )
        unavailable = await reader.read_history(
            resource_ids=(RESOURCE_ID,),
            event_families=("resource_event.resource_health",),
            lookback_seconds=3600,
        )

    assert empty.complete is True
    assert empty.events == ()
    assert empty.limitation is None
    assert unavailable.complete is False
    assert unavailable.events == ()
    assert unavailable.limitation == "source_unavailable"


async def test_history_reader_drops_out_of_scope_events() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _arm("other-service"),
                            "sourceType": "microsoft.resourcehealth/availabilitystatuses",
                            "availabilityState": "Unavailable",
                            "occurredTime": "2026-08-21T16:50:00Z",
                        }
                    ],
                    "count": 1,
                    "totalRecords": 1,
                    "resultTruncated": False,
                },
            )
        )
    ) as client:
        reader = AzureResourceEventHistoryReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceEventHistoryConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_history(
            resource_ids=(RESOURCE_ID,),
            event_families=("resource_event.resource_health",),
            lookback_seconds=3600,
        )

    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "provider_scope_mismatch"


async def test_history_reader_batches_exact_scope_and_demotes_partial_failure() -> None:
    names = tuple(f"service-{index:03d}" for index in range(65))
    resource_ids = tuple(
        "scope-0123456789abcdef/resource-group/example-rg/providers/"
        f"microsoft.app/containerapps/{name}"
        for name in names
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = json.loads(request.content)["query"]
        if _arm(names[-1]).casefold() in query.casefold():
            return httpx.Response(403)
        return httpx.Response(
            200,
            json={
                "data": [],
                "count": 0,
                "totalRecords": 0,
                "resultTruncated": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureResourceEventHistoryReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceEventHistoryConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_history(
            resource_ids=resource_ids,
            event_families=("resource_event.resource_health",),
            lookback_seconds=3600,
        )

    assert len(requests) == 2
    assert result.events == ()
    assert result.complete is False
    assert result.limitation == "source_coverage_incomplete"
