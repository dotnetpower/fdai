"""Contracts that keep a long-lived SSE stream from blocking graceful shutdown."""

from __future__ import annotations

import asyncio

from fdai_operator_service.streaming.live_stream import LiveStreamEvent, LiveStreamHub, _live_chunks
from fdai_operator_service.streaming.shutdown import STREAM_SHUTDOWN_STATE, shutting_down
from starlette.requests import Request


def _request(event: object | None) -> Request:
    application = type("_App", (), {"state": type("_State", (), {})()})()
    if event is not None:
        setattr(application.state, STREAM_SHUTDOWN_STATE, event)
    return Request({"type": "http", "method": "GET", "headers": [], "app": application})


def test_shutting_down_reports_false_without_a_published_event() -> None:
    assert shutting_down(_request(None)) is False
    assert shutting_down(Request({"type": "http", "method": "GET", "headers": []})) is False


def test_shutting_down_follows_the_published_event() -> None:
    event = asyncio.Event()
    request = _request(event)
    assert shutting_down(request) is False
    event.set()
    assert shutting_down(request) is True


async def test_live_chunks_stop_when_the_application_shuts_down() -> None:
    hub = LiveStreamHub()
    await hub.publish(LiveStreamEvent(event_id="event-1", payload={"sequence": 1}))
    shutdown = asyncio.Event()

    async def connected() -> bool:
        return False

    chunks = _live_chunks(
        hub=hub,
        is_disconnected=connected,
        is_shutting_down=shutdown.is_set,
        keepalive_seconds=60.0,
    )
    assert b"hello" in await anext(chunks)
    shutdown.set()

    remaining = [chunk async for chunk in chunks]
    assert all(b"hello" not in chunk for chunk in remaining)
