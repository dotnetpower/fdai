"""Regression coverage for signal-ordered Operator SSE shutdown."""

from __future__ import annotations

import asyncio
import http.client
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from types import FrameType, SimpleNamespace
from typing import cast

from fdai_operator_service.contracts import AsgiMessage, AsgiReceive, AsgiScope, AsgiSend
from fdai_operator_service.streaming.shutdown import STREAM_SHUTDOWN_STATE
from fdai_operator_service.streaming.signal_shutdown import StreamShutdownSignalMiddleware


async def test_lifespan_signal_notifies_streams_before_chaining_server_handler(
    monkeypatch,
) -> None:
    shutdown = asyncio.Event()
    messages: asyncio.Queue[AsgiMessage] = asyncio.Queue()
    sent: asyncio.Queue[AsgiMessage] = asyncio.Queue()
    chained_after_notification: list[int] = []

    class LifespanApplication:
        state = SimpleNamespace(**{STREAM_SHUTDOWN_STATE: shutdown})

        async def __call__(
            self,
            scope: AsgiScope,
            receive: AsgiReceive,
            send: AsgiSend,
        ) -> None:
            assert scope["type"] == "lifespan"
            assert (await receive())["type"] == "lifespan.startup"
            await send({"type": "lifespan.startup.complete"})
            assert (await receive())["type"] == "lifespan.shutdown"
            await send({"type": "lifespan.shutdown.complete"})

    def previous_handler(signum: int, _frame: FrameType | None) -> None:
        assert shutdown.is_set()
        chained_after_notification.append(signum)

    installed: dict[int, object] = {
        signal.SIGINT: previous_handler,
        signal.SIGTERM: previous_handler,
    }
    restored: list[tuple[int, object]] = []

    def install(signum: int, handler: object) -> object:
        previous = installed.get(signum, signal.SIG_DFL)
        installed[signum] = handler
        restored.append((signum, handler))
        return previous

    monkeypatch.setattr(signal, "signal", install)
    middleware = StreamShutdownSignalMiddleware(LifespanApplication())
    task = asyncio.create_task(
        middleware(
            {"type": "lifespan"},
            messages.get,
            sent.put,
        )
    )

    await messages.put({"type": "lifespan.startup"})
    assert (await sent.get())["type"] == "lifespan.startup.complete"
    handler = cast("signal._HANDLER", installed[signal.SIGTERM])
    assert callable(handler)
    handler(signal.SIGTERM, None)

    assert shutdown.is_set()
    assert chained_after_notification == [signal.SIGTERM]
    await messages.put({"type": "lifespan.shutdown"})
    assert (await sent.get())["type"] == "lifespan.shutdown.complete"
    await task
    assert installed[signal.SIGINT] is previous_handler
    assert installed[signal.SIGTERM] is previous_handler
    assert len(restored) == 4


def test_uvicorn_signal_drains_an_open_sse_connection_before_timeout() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    application = textwrap.dedent(
        """
        import asyncio
        import os
        from contextlib import asynccontextmanager

        import uvicorn
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import StreamingResponse
        from starlette.routing import Route

        from fdai_operator_service.streaming.shutdown import STREAM_SHUTDOWN_STATE
        from fdai_operator_service.streaming.signal_shutdown import StreamShutdownSignalMiddleware

        stop = asyncio.Event()

        @asynccontextmanager
        async def lifespan(app):
            setattr(app.state, STREAM_SHUTDOWN_STATE, stop)
            yield

        async def stream(_request: Request):
            async def events():
                yield b": connected\\n\\n"
                while not stop.is_set():
                    await asyncio.sleep(0.05)
                    yield b": keepalive\\n\\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        app = StreamShutdownSignalMiddleware(
            Starlette(routes=[Route("/stream", stream)], lifespan=lifespan)
        )
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ["FDAI_TEST_PORT"]),
            access_log=False,
            timeout_graceful_shutdown=1,
        )
        """
    )
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and test-owned program
        [sys.executable, "-c", application],
        env={**os.environ, "FDAI_TEST_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    output = process.communicate(timeout=1)[0]
                    raise AssertionError(f"Uvicorn did not become ready:\n{output}") from None
                time.sleep(0.02)

        connection.request("GET", "/stream")
        response = connection.getresponse()
        assert response.status == 200
        assert response.read(1) == b":"
        process.send_signal(signal.SIGTERM)
        output = process.communicate(timeout=5)[0]
    finally:
        connection.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)

    assert process.returncode in {0, -signal.SIGTERM}
    assert "timeout graceful shutdown exceeded" not in output
    assert "Exception in ASGI application" not in output
