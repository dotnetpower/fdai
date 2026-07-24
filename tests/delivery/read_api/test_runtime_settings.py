from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.routes.runtime_settings import make_runtime_settings_routes
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _principal(role: Role) -> Principal:
    return Principal(oid=f"{role.value.lower()}-1", roles=frozenset({role}))


def _client(service: RuntimeSettingsService, role: Role) -> TestClient:
    async def authorize_principal(request: Request) -> Principal:
        del request
        return _principal(role)

    return TestClient(
        Starlette(
            routes=make_runtime_settings_routes(
                service=service,
                authorize_principal=authorize_principal,
            )
        )
    )


def test_reader_can_view_but_cannot_update() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})
    client = _client(service, Role.READER)

    view = client.get("/runtime/settings")
    response = client.put(
        "/runtime/settings",
        json={"changes": {"logging.level": "DEBUG"}, "expected_revision": 0},
    )

    assert view.status_code == 200
    assert view.json()["can_manage"] is False
    assert response.status_code == 403


def test_owner_update_returns_revision_and_conflict() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})
    client = _client(service, Role.OWNER)
    payload: dict[str, Any] = {
        "changes": {"irp.enabled": True, "irp.budget_seconds": 45},
        "expected_revision": 0,
    }

    updated = client.put("/runtime/settings", json=payload)
    conflict = client.put("/runtime/settings", json=payload)

    assert updated.status_code == 200
    assert updated.json()["revision"] == 1
    assert updated.json()["can_manage"] is True
    assert conflict.status_code == 409


def test_invalid_payload_and_unknown_key_are_rejected() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})
    client = _client(service, Role.OWNER)

    missing_changes = client.put(
        "/runtime/settings",
        json={"expected_revision": 0},
    )
    unknown = client.put(
        "/runtime/settings",
        json={"changes": {"secret": "value"}, "expected_revision": 0},
    )

    assert missing_changes.status_code == 400
    assert unknown.status_code == 400


def test_invalid_environment_is_unavailable() -> None:
    service = RuntimeSettingsService(
        store=InMemoryStateStore(),
        env={"FDAI_LOG_LEVEL": "TRACE"},
    )
    client = _client(service, Role.READER)

    response = client.get("/runtime/settings")

    assert response.status_code == 503
