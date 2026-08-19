"""Lifecycle, readiness, HTTP bound, and redaction tests for the channel edge."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
)
from fdai_operator_service.families.conversation.channel_edge.runtime import (
    ChannelEdgeRuntime,
    create_channel_edge_app,
)
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressAction,
    SlackIngressError,
)
from httpx import ASGITransport, AsyncClient


class _Runtime:
    max_body_bytes = 32
    enabled_channels = frozenset({ChannelKind.SLACK, ChannelKind.TEAMS})

    def __init__(self) -> None:
        self.ready = True
        self.started = False
        self.closed = False
        self.slack_bodies: list[bytes] = []
        self.teams_bodies: list[bytes] = []
        self.slack_error: SlackIngressError | None = None

    async def start(self) -> None:
        self.started = True

    async def aclose(self) -> None:
        self.closed = True

    def accept_slack(
        self,
        *,
        body: bytes,
        headers: object,
        received_at: datetime,
    ) -> tuple[SlackIngressAction, str | None]:
        del headers, received_at
        if self.slack_error is not None:
            raise self.slack_error
        self.slack_bodies.append(body)
        return SlackIngressAction.ACCEPTED, None

    async def accept_teams(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> None:
        del authorization, received_at
        self.teams_bodies.append(body)


class _Lifecycle:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.workers_active = False

    async def start(self) -> None:
        self.events.append(f"start:{self.name}")
        self.workers_active = True

    async def aclose(self) -> None:
        self.events.append(f"close:{self.name}")
        self.workers_active = False

    def workers_ready(self) -> bool:
        return self.workers_active


class _Worker:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.ready = False

    async def start(self) -> None:
        self.events.append("start:worker")
        self.ready = True

    async def close(self) -> None:
        self.events.append("close:worker")
        self.ready = False


class _Queue:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.closed = asyncio.Event()
        self.fail = asyncio.Event()
        self.stopped = asyncio.Event()

    async def receive(self):  # type: ignore[no-untyped-def]
        self.events.append("start:consumer")
        waits = (
            asyncio.create_task(self.closed.wait()),
            asyncio.create_task(self.fail.wait()),
        )
        try:
            _done, pending = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if self.fail.is_set():
                raise RuntimeError("consumer failed")
            if False:
                yield None
        finally:
            self.stopped.set()

    async def close(self) -> None:
        self.events.append("close:queue")
        self.closed.set()


class _Pipeline:
    async def process(self, turn: AuthenticatedInboundTurn) -> None:
        del turn


class _Resource:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def aclose(self) -> None:
        self.events.append("close:resource")
        if self.fail:
            raise RuntimeError("resource close failed")


def _real_runtime(
    events: list[str],
    *,
    probe_result: bool = True,
) -> tuple[ChannelEdgeRuntime, _Queue]:
    transport = _Lifecycle("transport", events)
    bridge = _Lifecycle("bridge", events)
    worker = _Worker(events)
    queue = _Queue(events)

    async def startup() -> None:
        events.append("check:startup")

    async def readiness() -> bool:
        events.append("check:readiness")
        return probe_result

    runtime = ChannelEdgeRuntime(
        enabled_channels=frozenset({ChannelKind.SLACK}),
        pipeline=_Pipeline(),  # type: ignore[arg-type]
        worker=worker,  # type: ignore[arg-type]
        semantic_transport=transport,
        semantic_bridge=bridge,
        slack_queue=queue,  # type: ignore[arg-type]
        startup_checks=(startup,),
        readiness_checks=(readiness,),
        resources=(_Resource(events),),
        shutdown_grace_seconds=0.1,
    )
    return runtime, queue


async def test_routes_are_minimal_and_lifespan_closes_runtime() -> None:
    runtime = _Runtime()
    app = create_channel_edge_app(runtime)  # type: ignore[arg-type]
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            missing = await client.get("/incidents")
            slack = await client.post(
                "/webhooks/slack/events",
                content=b"{}",
                headers={"content-type": "application/json"},
            )

    assert runtime.started is True and runtime.closed is True
    assert live.status_code == ready.status_code == 200
    assert missing.status_code == 404
    assert slack.status_code == 202 and runtime.slack_bodies == [b"{}"]


async def test_readiness_drops_without_exposing_dependency_detail() -> None:
    runtime = _Runtime()
    runtime.ready = False
    app = create_channel_edge_app(runtime)  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


async def test_webhook_requires_json_and_streams_to_body_cap() -> None:
    runtime = _Runtime()
    app = create_channel_edge_app(runtime)  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        media = await client.post("/webhooks/slack/events", content=b"{}")
        large = await client.post(
            "/webhooks/teams/activities",
            content=b"x" * 33,
            headers={"content-type": "application/json"},
        )

    assert media.status_code == 415
    assert large.status_code == 413
    assert not runtime.slack_bodies and not runtime.teams_bodies


async def test_ingress_error_exposes_only_code() -> None:
    runtime = _Runtime()
    runtime.slack_error = SlackIngressError(
        "secret provider detail",
        code="invalid_signature",
        http_status=401,
    )
    app = create_channel_edge_app(runtime)  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/slack/events",
            content=b"{}",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "invalid_signature"}}
    assert "secret provider detail" not in response.text


async def test_oversized_teams_authorization_is_rejected_before_ingress() -> None:
    runtime = _Runtime()
    app = create_channel_edge_app(runtime)  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/teams/activities",
            content=b"{}",
            headers={
                "content-type": "application/json",
                "authorization": "x" * 16_385,
            },
        )

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "authentication_too_large"}}
    assert not runtime.teams_bodies


@pytest.mark.parametrize("path", ["/webhooks/slack/events", "/webhooks/teams/activities"])
async def test_webhooks_do_not_accept_get(path: str) -> None:
    app = create_channel_edge_app(_Runtime())  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 405


async def test_real_runtime_orders_dependencies_before_consumer_and_closes_reverse() -> None:
    events: list[str] = []
    runtime, _queue = _real_runtime(events)

    await runtime.start()
    assert runtime.ready is True
    assert events[:6] == [
        "start:transport",
        "start:bridge",
        "check:startup",
        "check:readiness",
        "start:worker",
        "start:consumer",
    ]
    await runtime.aclose()
    assert runtime.ready is False
    assert events[-5:] == [
        "close:queue",
        "close:worker",
        "close:bridge",
        "close:transport",
        "close:resource",
    ]


async def test_real_runtime_rolls_back_when_required_probe_fails() -> None:
    events: list[str] = []
    runtime, _queue = _real_runtime(events, probe_result=False)

    with pytest.raises(RuntimeError, match="required dependency"):
        await runtime.start()

    assert runtime.ready is False
    assert "start:worker" not in events
    assert events[-4:] == [
        "close:worker",
        "close:bridge",
        "close:transport",
        "close:resource",
    ]


async def test_real_runtime_drops_readiness_when_consumer_dies() -> None:
    events: list[str] = []
    runtime, queue = _real_runtime(events)
    await runtime.start()

    queue.fail.set()
    await queue.stopped.wait()

    assert runtime.ready is False
    await runtime.aclose()


async def test_real_runtime_closes_later_resources_after_close_error() -> None:
    events: list[str] = []
    runtime, _queue = _real_runtime(events)
    runtime._resources = (  # noqa: SLF001 - exact shutdown fault injection
        _Resource(events),
        _Resource(events, fail=True),
    )
    await runtime.start()

    with pytest.raises(RuntimeError, match="resource close failed"):
        await runtime.aclose()

    assert events[-2:] == ["close:resource", "close:resource"]


async def test_real_runtime_closes_owned_dependencies_only_once() -> None:
    events: list[str] = []
    runtime, _queue = _real_runtime(events)
    await runtime.start()

    await runtime.aclose()
    await runtime.aclose()

    assert events.count("close:queue") == 1
    assert events.count("close:worker") == 1
    assert events.count("close:bridge") == 1
    assert events.count("close:transport") == 1
    assert events.count("close:resource") == 1
    with pytest.raises(RuntimeError, match="cannot restart"):
        await runtime.start()
