from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.notification_templates import (
    make_notification_template_route,
)


def _client() -> TestClient:
    async def authorize(request: Request) -> str:
        del request
        return "reader-1"

    return TestClient(Starlette(routes=[make_notification_template_route(authorize=authorize)]))


def test_incident_opened_preview_uses_production_renderer() -> None:
    response = _client().get("/notification-templates/incident-opened")

    assert response.status_code == 200
    payload = response.json()
    assert payload["key"] == "incident-opened"
    assert payload["subject"] == "[SEV2] Incident opened"
    assert "Correlated evidence: 8" in payload["plain_text"]
    assert "A new operational incident is open." in payload["html"]
    assert "00000000-0000-0000-0000-000000000000" in payload["html"]
    assert "/approve" not in payload["html"]
    assert "/execute" not in payload["html"]


def test_incident_opened_preview_is_get_only() -> None:
    assert _client().post("/notification-templates/incident-opened").status_code == 405
