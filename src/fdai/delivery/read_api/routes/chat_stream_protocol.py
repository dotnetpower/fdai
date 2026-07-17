"""SSE framing, fallback chunking, and idle heartbeat transport."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any, Final

DEFAULT_STREAM_HEARTBEAT_S: Final[float] = 15.0


def _sse(event: str, data: dict[str, Any]) -> bytes:
    """Format one Server-Sent Event frame (``event:`` + ``data:`` + blank)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _sse_heartbeat() -> bytes:
    """SSE comment frame - ignored by ``EventSource``, kept by intermediaries."""
    return b": ping\n\n"


_CHUNK_RE: Final = re.compile(r"\s*\S{1,4}|\s+$")


def _chunk_answer_for_stream(text: str) -> list[str]:
    """Split ``text`` into ~4-char groups (whitespace kept with the following
    token) so a non-streaming backend's answer types in progressively when
    replayed over SSE. Mirrors the client-side typewriter in
    ``console/src/deck/backend.ts::chunksForTypewriter`` so the same visual
    cadence applies whether the deterministic fallback runs client-side or
    the server had to replay a one-shot ``answer`` reply. Never returns an
    empty list - falls back to ``[text]`` for pathological inputs so the
    caller always emits at least one frame."""
    out = [m.group(0) for m in _CHUNK_RE.finditer(text)]
    return out if out else [text]


async def _with_sse_heartbeats(
    source: AsyncIterator[dict[str, Any]],
    *,
    interval: float,
    queue_maxsize: int = 64,
) -> AsyncIterator[dict[str, Any] | None]:
    """Yield items from ``source``; emit ``None`` every ``interval`` idle seconds.

    Uses a bounded queue-backed pump so the underlying async iterator is
    never cancelled mid-await (which could drop the next token) AND a
    fast upstream cannot inflate memory if the SSE consumer is slow -
    ``queue_maxsize`` provides natural backpressure. ``None`` items are
    the caller's heartbeat sentinel - callers translate them into an SSE
    comment frame, real dict items into ``event:``/``data:`` frames.

    Cancellation contract: when the consuming generator is closed (client
    disconnect, StreamingResponse teardown), the ``finally`` block cancels
    the pump task and awaits it. The pump's ``async for`` loop then
    unwinds and Python calls ``aclose()`` on ``source``, so an httpx
    streaming connection is released - no connection leak.
    """
    import asyncio

    queue: asyncio.Queue[tuple[str, dict[str, Any] | BaseException | None]] = asyncio.Queue(
        maxsize=max(1, queue_maxsize)
    )
    _end: Final = "end"
    _item: Final = "item"
    _err: Final = "err"

    async def _pump() -> None:
        try:
            async for x in source:
                await queue.put((_item, x))
        except asyncio.CancelledError:
            # Consumer went away; unwinding the async for closes `source`.
            raise
        except BaseException as exc:  # re-raise on the consumer side
            try:
                # Preserve the ORIGINAL exception object so an HTTPException
                # from an upstream 4xx surfaces its real ``.detail`` at the
                # SSE handler, instead of being flattened into a generic
                # "chat stream failed" via repr().
                await queue.put((_err, exc))
            except asyncio.CancelledError:
                pass
            return
        try:
            await queue.put((_end, None))
        except asyncio.CancelledError:
            pass

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                kind, val = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield None  # heartbeat
                continue
            if kind == _end:
                return
            if kind == _err:
                # Re-raise the original exception on the consumer side so the
                # SSE handler's `except HTTPException` branch catches an
                # upstream 4xx with its real detail. `val` is always a
                # BaseException here by construction in `_pump`.
                if isinstance(val, BaseException):
                    raise val
                raise RuntimeError(f"stream source failed: {val!r}")
            # `_item` branch: val is the dict[str, Any] we forward downstream.
            yield val  # type: ignore[misc]
    finally:
        if not pump_task.done():
            pump_task.cancel()
        try:
            await pump_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
            pass
