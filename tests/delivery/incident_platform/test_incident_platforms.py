"""PagerDuty and ServiceNow incident platform adapters."""

from __future__ import annotations

from typing import Any

import httpx

from fdai.delivery.incident_platform import (
    PagerDutyIncidentPlatform,
    PagerDutyIncidentPlatformConfig,
    ServiceNowIncidentPlatform,
    ServiceNowIncidentPlatformConfig,
)
from fdai.shared.providers.incident_platform import ExternalIncidentStatus


async def _token() -> str:
    return "test-token"


async def test_pagerduty_lists_and_updates_incidents() -> None:
    requests: list[httpx.Request] = []
    row: dict[str, Any] = {
        "id": "P1",
        "title": "API latency",
        "urgency": "high",
        "status": "triggered",
        "created_at": "2026-07-20T10:00:00Z",
        "updated_at": "2026-07-20T11:00:00Z",
        "service": {"id": "S1"},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"incidents": [row]})
        if request.url.path.endswith("/notes"):
            return httpx.Response(201, json={"note": {"id": "N1"}})
        updated = {**row, "status": "acknowledged"}
        return httpx.Response(200, json={"incident": updated})

    provider = PagerDutyIncidentPlatform(
        config=PagerDutyIncidentPlatformConfig(from_email="operator@example.com"),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    incidents = await provider.list_active(limit=10)
    acknowledged = await provider.acknowledge("P1")
    await provider.add_note("P1", "Investigation started")

    assert incidents[0].status is ExternalIncidentStatus.TRIGGERED
    assert acknowledged.status is ExternalIncidentStatus.ACKNOWLEDGED
    assert [request.method for request in requests] == ["GET", "PUT", "POST"]
    assert all(request.headers["Authorization"] == "Token token=test-token" for request in requests)


async def test_servicenow_lists_resolves_and_adds_notes() -> None:
    requests: list[httpx.Request] = []
    row: dict[str, Any] = {
        "sys_id": "abc",
        "number": "INC001",
        "short_description": "Database unavailable",
        "priority": "1",
        "state": "1",
        "sys_created_on": "2026-07-20 10:00:00",
        "sys_updated_on": "2026-07-20 11:00:00",
        "business_service": {"value": "db-service"},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"result": [row]})
        body = {**row, "state": "6"}
        return httpx.Response(200, json={"result": body})

    provider = ServiceNowIncidentPlatform(
        config=ServiceNowIncidentPlatformConfig(instance_url="https://example.service-now.com"),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    incidents = await provider.list_active(limit=10)
    resolved = await provider.resolve("abc")
    await provider.add_note("abc", "Recovered")

    assert incidents[0].service_ref == "db-service"
    assert resolved.status is ExternalIncidentStatus.RESOLVED
    assert [request.method for request in requests] == ["GET", "PATCH", "PATCH"]
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
