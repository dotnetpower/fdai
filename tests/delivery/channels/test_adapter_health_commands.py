from __future__ import annotations

from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation.adapter_health import (
    AdapterHealthService,
    InMemoryAdapterHealthAuditSink,
)
from fdai.delivery.channels.adapter_health_commands import (
    make_adapter_health_command_routes,
)
from fdai.shared.providers.conversation_delivery import InMemoryConversationDeliveryStore

NOW = datetime(2026, 7, 20, 20, 30, tzinfo=UTC)


class _Authenticator:
    async def authenticate(self, request: Request) -> str | None:
        token = request.headers.get("authorization")
        return "owner-example" if token == "Bearer owner" else None


class _Authorizer:
    def can_manage_adapter(self, *, actor_id: str, adapter_id: str) -> bool:
        return actor_id == "owner-example" and adapter_id == "slack"


def _client() -> TestClient:
    service = AdapterHealthService(
        store=InMemoryConversationDeliveryStore(),
        audit=InMemoryAdapterHealthAuditSink(),
        authorizer=_Authorizer(),
    )
    return TestClient(
        Starlette(
            routes=list(
                make_adapter_health_command_routes(
                    service=service,
                    authenticator=_Authenticator(),
                    clock=lambda: NOW,
                )
            )
        )
    )


def test_adapter_commands_require_separate_authentication() -> None:
    client = _client()
    response = client.post(
        "/commands/adapters/slack/pause",
        json={"channel_kind": "slack", "reason": "maintenance"},
    )
    assert response.status_code == 401


def test_authorized_pause_status_and_manual_resume() -> None:
    client = _client()
    headers = {"Authorization": "Bearer owner"}

    paused = client.post(
        "/commands/adapters/slack/pause",
        json={"channel_kind": "slack", "reason": "maintenance"},
        headers=headers,
    )
    status = client.get("/commands/adapters/slack", headers=headers)
    resumed = client.post(
        "/commands/adapters/slack/resume",
        json={"reason": "provider verified"},
        headers=headers,
    )

    assert paused.status_code == status.status_code == resumed.status_code == 200
    assert paused.json()["mode"] == status.json()["mode"] == "paused"
    assert resumed.json()["mode"] == "closed"
    assert resumed.json()["requested_by"] == "owner-example"
