from __future__ import annotations

from datetime import UTC, datetime

import httpx
from starlette.applications import Starlette
from starlette.requests import Request

from fdai.core.conversation import BusyInputCoordinator, BusyInputMode, InMemoryBusyInputStore
from fdai.delivery.read_api.routes.busy_input import make_busy_input_routes

_NOW = datetime(2026, 7, 20, 15, tzinfo=UTC)


async def _authorize(request: Request) -> str:
    return request.headers.get("x-test-principal", "operator-one")


def _app(coordinator: BusyInputCoordinator) -> Starlette:
    return Starlette(
        routes=[
            *make_busy_input_routes(coordinator=coordinator, authorize=_authorize, now=lambda: _NOW)
        ]
    )


async def test_queue_ack_duplicate_and_pending_inspection() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.QUEUE,
    )
    transport = httpx.ASGITransport(app=_app(coordinator))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "session_id": "session-one",
            "content": "check the latest evidence",
            "kind": "prose",
            "input_id": "input-one",
            "idempotency_key": "idempotency-one",
            "expires_in_seconds": 60,
        }
        accepted = await client.post("/chat/busy-input", json=payload)
        duplicate = await client.post("/chat/busy-input", json=payload)
        inspected = await client.get(
            "/chat/busy-input",
            params={"session_id": "session-one"},
        )

    assert accepted.status_code == 202
    assert accepted.json() == {
        "disposition": "queued",
        "session_id": "session-one",
        "input_id": "input-one",
        "sequence": 0,
        "reason": None,
        "duplicate": False,
    }
    assert duplicate.json()["duplicate"] is True
    assert inspected.json()["pending"] == [
        {
            "input_id": "input-one",
            "sequence": 0,
            "disposition": "queued",
            "kind": "prose",
            "content": "check the latest evidence",
            "expires_at": "2026-07-20T15:01:00+00:00",
        }
    ]


async def test_mode_preference_drives_active_interrupt_and_cancel_current() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    transport = httpx.ASGITransport(app=_app(coordinator))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        mode = await client.put(
            "/chat/busy-input/mode",
            json={"session_id": "session-one", "mode": "interrupt"},
        )
        active = await coordinator.begin_turn(
            session_id="session-one",
            turn_id="turn-one",
            principal_id="operator-one",
        )
        cancelled = await client.post(
            "/chat/busy-input/cancel-current",
            json={"session_id": "session-one"},
        )

    assert mode.json() == {"session_id": "session-one", "mode": "interrupt"}
    assert cancelled.status_code == 202
    assert cancelled.json() == {"session_id": "session-one", "cancelled": True}
    assert active.cancel_event.is_set()


async def test_cross_owner_state_is_hidden_and_expiry_is_bounded() -> None:
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.QUEUE,
    )
    transport = httpx.ASGITransport(app=_app(coordinator))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        hidden = await client.get(
            "/chat/busy-input",
            params={"session_id": "session-one"},
            headers={"x-test-principal": "operator-two"},
        )
        invalid_expiry = await client.post(
            "/chat/busy-input",
            json={
                "session_id": "session-one",
                "content": "later",
                "input_id": "input-one",
                "idempotency_key": "idempotency-one",
                "expires_in_seconds": 3_601,
            },
        )

    assert hidden.status_code == 404
    assert invalid_expiry.status_code == 400
