"""HTTP boundary tests for the global kill-switch command route."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.rbac.kill_switch_command import KillSwitchCommandService
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.operator_api.routes.kill_switch import make_kill_switch_route
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _client(role: Role) -> tuple[TestClient, InMemoryStateStore]:
    store = InMemoryStateStore()

    async def authorize(_request: object) -> Principal:
        return Principal(oid=f"user-{role.value.lower()}", roles=frozenset({role}))

    app = Starlette(
        routes=[
            make_kill_switch_route(
                service=KillSwitchCommandService(store=store),
                authorize_principal=authorize,  # type: ignore[arg-type]
            )
        ]
    )
    return TestClient(app), store


def _payload(engaged: bool = True) -> dict[str, object]:
    return {
        "engaged": engaged,
        "reason": "Emergency containment during an active incident.",
        "request_id": "kill-request-1",
    }


def test_owner_can_engage_kill_switch() -> None:
    client, store = _client(Role.OWNER)

    response = client.post("/system/kill-switch", json=_payload())

    assert response.status_code == 200
    assert response.json()["state"]["engaged"] is True
    assert len(store.audit_entries) == 1


def test_break_glass_can_engage_kill_switch() -> None:
    client, _store = _client(Role.BREAK_GLASS)

    response = client.post("/system/kill-switch", json=_payload())

    assert response.status_code == 200


def test_reader_cannot_change_kill_switch() -> None:
    client, store = _client(Role.READER)

    response = client.post("/system/kill-switch", json=_payload())

    assert response.status_code == 403
    assert store.audit_entries == ()


def test_invalid_payload_is_rejected_without_audit() -> None:
    client, store = _client(Role.OWNER)

    response = client.post("/system/kill-switch", json={"engaged": "yes"})

    assert response.status_code == 400
    assert store.audit_entries == ()
