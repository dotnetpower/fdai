"""Bounded Azure Resource Health collection reader tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from fdai.delivery.azure.resource_health_collection import (
    AzureResourceHealthCollectionConfig,
    AzureResourceHealthCollectionReader,
)
from fdai.shared.providers.workload_identity import IdentityToken

SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
NOW = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
RESOURCE_IDS = (
    "scope-0123456789abcdef/resource-group/example-rg/providers/"
    "microsoft.app/containerapps/service-a",
    "scope-0123456789abcdef/resource-group/example-rg/providers/"
    "microsoft.app/containerapps/service-b",
)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        assert audience == "https://management.azure.com/.default"
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(minutes=5),
            audience=audience,
        )


def _arm(name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
        f"providers/microsoft.app/containerapps/{name}"
    )


async def test_reader_binds_arg_rows_back_to_exact_logical_resources() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "targetResourceId": _arm("service-a"),
                        "availabilityState": "Unavailable",
                        "reasonType": "PlatformInitiated",
                        "occurredTime": "2026-08-21T14:55:00Z",
                        "reportedTime": "2026-08-21T14:56:00Z",
                    },
                    {
                        "targetResourceId": _arm("service-b"),
                        "availabilityState": "Available",
                        "reasonType": "",
                        "occurredTime": "2026-08-21T14:55:00Z",
                        "reportedTime": "2026-08-21T14:56:00Z",
                    },
                ],
                "count": 2,
                "totalRecords": 2,
                "resultTruncated": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureResourceHealthCollectionReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthCollectionConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_current(resource_ids=RESOURCE_IDS)

    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    body = json.loads(requests[0].content)
    assert body["subscriptions"] == [SUBSCRIPTION_ID]
    assert _arm("service-a").casefold() in body["query"].casefold()
    assert _arm("service-b").casefold() in body["query"].casefold()
    assert result.resource_ids == RESOURCE_IDS
    assert result.complete is True
    assert result.limitation is None
    assert tuple(item.resource_id for item in result.observations) == RESOURCE_IDS
    assert result.observations[0].availability_state == "unavailable"
    assert result.observations[0].reason_kind == "platform_initiated"
    assert result.observations[0].observed_at == datetime(2026, 8, 21, 14, 56, tzinfo=UTC)
    assert result.observations[0].evidence_ref.startswith("azure-resource-health:")


async def test_reader_preserves_known_rows_and_marks_missing_coverage_incomplete() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _arm("service-a"),
                            "availabilityState": "Degraded",
                            "reasonType": "PlatformInitiated",
                            "reportedTime": "2026-08-21T14:57:00Z",
                        }
                    ],
                    "count": 1,
                    "totalRecords": 1,
                    "resultTruncated": False,
                },
            )
        )
    ) as client:
        reader = AzureResourceHealthCollectionReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthCollectionConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_current(resource_ids=RESOURCE_IDS)

    assert result.complete is False
    assert result.limitation == "resource_health_coverage_incomplete"
    assert len(result.observations) == 1


async def test_reader_drops_out_of_scope_rows_and_marks_provider_mismatch() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "targetResourceId": _arm("service-a"),
                            "availabilityState": "Available",
                            "reportedTime": "2026-08-21T14:58:00Z",
                        },
                        {
                            "targetResourceId": _arm("other-service"),
                            "availabilityState": "Unavailable",
                            "reportedTime": "2026-08-21T14:58:00Z",
                        },
                    ],
                    "count": 2,
                    "totalRecords": 2,
                    "resultTruncated": False,
                },
            )
        )
    ) as client:
        reader = AzureResourceHealthCollectionReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthCollectionConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_current(resource_ids=RESOURCE_IDS)

    assert result.complete is False
    assert result.limitation == "provider_scope_mismatch"
    assert tuple(item.resource_id for item in result.observations) == (RESOURCE_IDS[0],)


async def test_reader_converts_provider_failure_to_typed_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403))
    ) as client:
        reader = AzureResourceHealthCollectionReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthCollectionConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_current(resource_ids=RESOURCE_IDS)

    assert result.complete is False
    assert result.limitation == "source_unavailable"
    assert result.observations == ()


async def test_reader_batches_exact_scope_and_demotes_partial_batch_failure() -> None:
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
        rows = [
            {
                "targetResourceId": _arm(name),
                "availabilityState": "Available",
                "reasonType": "",
                "reportedTime": "2026-08-21T14:58:00Z",
            }
            for name in names[:-1]
            if _arm(name).casefold() in query.casefold()
        ]
        return httpx.Response(
            200,
            json={
                "data": rows,
                "count": len(rows),
                "totalRecords": len(rows),
                "resultTruncated": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = AzureResourceHealthCollectionReader(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureResourceHealthCollectionConfig(subscription_id=SUBSCRIPTION_ID),
            now=lambda: NOW,
        )
        result = await reader.read_current(resource_ids=resource_ids)

    assert len(requests) == 2
    assert len(result.observations) == 64
    assert result.complete is False
    assert result.limitation == "resource_health_coverage_incomplete"
