"""Entitlement stamp tests.

The stamp carries Core's watermark notice to the Console. These prove that only an
authenticated response carries it, that no route, role, or stored value outside the
closed vocabulary hides the watermark, and that a missing, stale, or unreadable
state fails closed to `not-activated`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.entitlement_stamp import (
    EntitlementStamp,
    EntitlementStampMiddleware,
    EntitlementState,
    current_notice,
    mark_request_authenticated,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (None, "not-activated"),
        (EntitlementState("none", _NOW), "none"),
        (EntitlementState("evaluation-ended", _NOW - timedelta(minutes=4)), "evaluation-ended"),
        (EntitlementState("not-activated", _NOW), "not-activated"),
        (EntitlementState("hidden", _NOW), "not-activated"),
        (EntitlementState("", _NOW), "not-activated"),
        (EntitlementState("none", _NOW - timedelta(minutes=6)), "not-activated"),
        (EntitlementState("none", _NOW + timedelta(minutes=6)), "not-activated"),
        (EntitlementState("none", datetime(2026, 10, 1, 12, 0)), "not-activated"),
    ],
)
def test_only_a_fresh_notice_in_the_closed_vocabulary_is_stamped(
    state: EntitlementState | None, expected: str
) -> None:
    assert current_notice(state, now=_NOW) == expected


class _Source:
    def __init__(self, *states: EntitlementState | None | Exception) -> None:
        self._states = list(states)
        self.reads = 0
        self.gate: asyncio.Event | None = None

    async def latest(self) -> EntitlementState | None:
        self.reads += 1
        if self.gate is not None:
            await self.gate.wait()
        state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
        if isinstance(state, Exception):
            raise state
        return state


class _Clock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def monotonic(self) -> float:
        return self.seconds


def _stamp(source: _Source | None, clock: _Clock) -> EntitlementStamp:
    return EntitlementStamp(source, clock=lambda: _NOW, monotonic=clock.monotonic)


async def test_the_stamp_reads_once_per_refresh_interval() -> None:
    clock = _Clock()
    source = _Source(EntitlementState("none", _NOW), EntitlementState("evaluation-ended", _NOW))
    stamp = _stamp(source, clock)

    assert await stamp.notice() == "none"
    clock.seconds = 14.0
    assert await stamp.notice() == "none"
    clock.seconds = 15.0
    assert await stamp.notice() == "evaluation-ended"
    assert source.reads == 2


async def test_a_failed_read_keeps_the_last_state_and_an_absent_row_clears_it() -> None:
    clock = _Clock()
    source = _Source(
        EntitlementState("none", _NOW),
        RuntimeError("database unavailable"),
        None,
    )
    stamp = _stamp(source, clock)

    assert await stamp.notice() == "none"
    clock.seconds = 20.0
    assert await stamp.notice() == "none"
    clock.seconds = 40.0
    assert await stamp.notice() == "not-activated"


async def test_a_slow_read_times_out_to_the_missing_state() -> None:
    source = _Source(EntitlementState("none", _NOW))
    source.gate = asyncio.Event()
    stamp = EntitlementStamp(source, clock=lambda: _NOW, read_timeout_seconds=0.01)

    assert await stamp.notice() == "not-activated"


async def test_concurrent_responses_share_one_read() -> None:
    clock = _Clock()
    source = _Source(EntitlementState("none", _NOW))
    source.gate = asyncio.Event()
    stamp = _stamp(source, clock)

    pending = [asyncio.create_task(stamp.notice()) for _ in range(5)]
    await asyncio.sleep(0)
    source.gate.set()

    assert await asyncio.gather(*pending) == ["none"] * 5
    assert source.reads == 1


async def test_no_source_stamps_not_activated() -> None:
    assert await _stamp(None, _Clock()).notice() == "not-activated"


def _app(stamp: EntitlementStamp, authenticator: OperatorAuthenticator | None = None) -> Starlette:
    async def open_route(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def authenticated(_: Request) -> Response:
        mark_request_authenticated()
        return JSONResponse({"ok": True})

    def authenticated_in_thread(_: Request) -> Response:
        mark_request_authenticated()
        return JSONResponse({"ok": True})

    async def overriding(_: Request) -> Response:
        mark_request_authenticated()
        return JSONResponse({"ok": True}, headers={"X-FDAI-Entitlement": "none"})

    async def principal(request: Request) -> Response:
        assert authenticator is not None
        found = authenticator.authenticate(request.headers.get("authorization"))
        return JSONResponse({"roles": sorted(role.value for role in found.roles)})

    return Starlette(
        routes=[
            Route("/open", open_route),
            Route("/authenticated", authenticated),
            Route("/authenticated-in-thread", authenticated_in_thread),
            Route("/overriding", overriding),
            Route("/principal", principal),
        ],
        middleware=[Middleware(EntitlementStampMiddleware, stamp=stamp)],
    )


def test_only_authenticated_responses_carry_the_stamp() -> None:
    clock = _Clock()
    client = TestClient(_app(_stamp(_Source(EntitlementState("evaluation-ended", _NOW)), clock)))

    assert "x-fdai-entitlement" not in client.get("/open").headers
    assert client.get("/authenticated").headers["x-fdai-entitlement"] == "evaluation-ended"
    assert (
        client.get("/authenticated-in-thread").headers["x-fdai-entitlement"] == "evaluation-ended"
    )
    assert "x-fdai-entitlement" not in client.get("/open").headers


def test_a_route_cannot_replace_the_stamp() -> None:
    client = TestClient(_app(_stamp(None, _Clock())))

    response = client.get("/overriding")

    assert response.headers.get_list("x-fdai-entitlement") == ["not-activated"]


@pytest.mark.parametrize(
    "claims",
    [
        {"oid": "reader", "idtyp": "user", "roles": ["Reader"]},
        {"oid": "owner", "idtyp": "user", "roles": ["Owner"]},
        {"oid": "workload", "idtyp": "app", "roles": ["Reader"]},
    ],
)
def test_every_verified_principal_receives_the_stamp(claims: Mapping[str, object]) -> None:
    authenticator = OperatorAuthenticator(verifier=lambda _token: claims, group_ids={})
    client = TestClient(
        _app(_stamp(_Source(EntitlementState("evaluation-ended", _NOW)), _Clock()), authenticator),
        raise_server_exceptions=False,
    )

    verified = client.get("/principal", headers={"Authorization": "Bearer token"})
    unverified = client.get("/principal")

    assert verified.status_code == 200
    assert verified.headers["x-fdai-entitlement"] == "evaluation-ended"
    assert "x-fdai-entitlement" not in unverified.headers
