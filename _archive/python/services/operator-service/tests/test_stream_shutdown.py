"""Contracts that keep a long-lived SSE stream from blocking graceful shutdown."""

from __future__ import annotations

import asyncio

import pytest
from fdai_operator_service.streaming.live_stream import LiveStreamEvent, LiveStreamHub, _live_chunks
from fdai_operator_service.streaming.shutdown import (
    STREAM_SHUTDOWN_STATE,
    next_or_shutdown,
    shutting_down,
    sleep_or_shutdown,
)
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


async def test_next_or_shutdown_returns_the_next_event() -> None:
    async def source():
        yield "first"
        yield "second"

    stream = source()
    stop = asyncio.Event()
    assert await next_or_shutdown(stream, stop) == "first"
    assert await next_or_shutdown(stream, stop) == "second"
    assert await next_or_shutdown(stream, stop) is None


async def test_next_or_shutdown_releases_an_idle_stream_on_shutdown() -> None:
    """An idle conversation stream must not hold graceful shutdown open."""

    async def idle():
        await asyncio.Event().wait()
        yield "never"

    stream = idle()
    stop = asyncio.Event()
    waiter = asyncio.create_task(next_or_shutdown(stream, stop))
    await asyncio.sleep(0)
    assert not waiter.done()

    stop.set()
    assert await asyncio.wait_for(waiter, timeout=1.0) is None


async def test_next_or_shutdown_closes_the_source_when_its_caller_is_cancelled() -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    async def idle():
        try:
            started.set()
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.set()

    waiter = asyncio.create_task(next_or_shutdown(idle(), asyncio.Event()))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert closed.is_set()


async def test_next_or_shutdown_without_a_published_event_still_iterates() -> None:
    async def source():
        yield "only"

    stream = source()
    assert await next_or_shutdown(stream, None) == "only"
    assert await next_or_shutdown(stream, None) is None


async def test_live_chunks_release_an_idle_keepalive_wait_on_shutdown() -> None:
    hub = LiveStreamHub()
    shutdown = asyncio.Event()

    async def connected() -> bool:
        return False

    chunks = _live_chunks(
        hub=hub,
        is_disconnected=connected,
        is_shutting_down=shutdown.is_set,
        shutdown=shutdown,
        keepalive_seconds=60.0,
    )
    assert b"hello" in await anext(chunks)
    # The stream is now idle inside a 60-second keepalive wait; shutdown must end it at once.
    pending = asyncio.ensure_future(anext(chunks))
    await asyncio.sleep(0)
    shutdown.set()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pending, timeout=1.0)


async def test_sleep_or_shutdown_ends_the_poll_interval_when_shutdown_begins() -> None:
    shutdown = asyncio.Event()
    waiting = asyncio.ensure_future(sleep_or_shutdown(60.0, shutdown))
    await asyncio.sleep(0)
    shutdown.set()

    assert await asyncio.wait_for(waiting, timeout=1.0) is True
    assert await sleep_or_shutdown(60.0, shutdown) is True
    assert await sleep_or_shutdown(0.0, asyncio.Event()) is False
    assert await sleep_or_shutdown(0.0, None) is False


async def test_inventory_invalidation_events_stop_polling_on_shutdown() -> None:
    from fdai_operator_service.families.operations import factory as operations_factory
    from fdai_operator_service.families.operations.contracts import ReplayBatch, ReplayQuery
    from fdai_service_contracts import OperatorPrincipal

    replays: list[ReplayQuery] = []

    class _Reader:
        async def replay(self, query: ReplayQuery) -> ReplayBatch:
            replays.append(query)
            return ReplayBatch(events=(), watermark=0)

    shutdown = asyncio.Event()
    chunks = operations_factory._inventory_invalidation_events(  # noqa: SLF001
        _Reader(),
        OperatorPrincipal(subject_id="reader-oid", roles=frozenset()),
        None,
        ReplayBatch(events=(), watermark=0),
        stop=shutdown,
    )
    pending = asyncio.ensure_future(anext(chunks))
    await asyncio.sleep(0)
    shutdown.set()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pending, timeout=1.0)
    assert replays == []
