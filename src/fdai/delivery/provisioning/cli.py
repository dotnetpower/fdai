"""Surface-A bootstrap entrypoint - run the Genesis screen off a local apply.

At Day-1 none of the runtime exists yet (read-API, event bus, RBAC, console
hosting are the very resources being provisioned), so the in-product SSE path
cannot serve the Genesis screen. This module is the *ephemeral* bootstrap: for
the lifetime of one ``terraform apply`` it

1. hosts a **minimal** Starlette app - just the read-only ``provision.*`` SSE
   route plus the static Genesis page - with an anonymous authorizer (Day-1 is
   a single local operator; there is no identity provider yet),
2. pumps ``terraform apply -json`` from **stdin** through the pure
   :func:`~fdai.delivery.provisioning.serve.pump_provision_events` into that
   app's in-memory sink, and
3. lingers briefly so the browser renders the finale, then exits.

It adds no persistent component: the process is born with the apply and dies
with it (scale-to-zero, literally). Subprocess ownership stays with the caller
(``azd up ... | python -m fdai.delivery.provisioning``); the core never spawns
Terraform. The transport is the existing
:class:`~fdai.delivery.read_api.streaming.provision_stream.ProvisionPublisher`
seam, so the in-product surface (event bus) and this bootstrap surface (local
stdin) share one contract.

Usage::

    azd up | python -m fdai.delivery.provisioning --genesis-html path/to.html
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Route

from fdai.delivery.provisioning.serve import aiter_json_lines, pump_provision_events
from fdai.delivery.provisioning.terraform_bridge import (
    DEFAULT_CONSOLE_OUTPUT,
    DEFAULT_WAITING_THRESHOLD_SECONDS,
    TerraformProvisionBridge,
)
from fdai.delivery.read_api.streaming.provision_stream import (
    DEFAULT_CHANNEL,
    DEFAULT_ROUTE_PATH,
    SseProvisionPublisher,
    make_provision_stream_route,
)
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.testing.sse import InMemorySseSink

_BOOTSTRAP_PRINCIPAL = "bootstrap"
DEFAULT_LINGER_SECONDS = 6.0
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770


async def _anonymous_authorize(_request: Request) -> str:
    """Authorizer for the Day-1 bootstrap app.

    Day-1 is a single local operator on localhost with no identity provider
    yet (RBAC is still being provisioned), so the SSE route resolves to a
    fixed anonymous principal. The route stays read-only regardless.
    """
    return _BOOTSTRAP_PRINCIPAL


def _genesis_endpoint(html_path: Path) -> Callable[[Request], Awaitable[Response]]:
    async def _serve_genesis(_request: Request) -> Response:
        return FileResponse(html_path, media_type="text/html")

    return _serve_genesis


def build_bootstrap_app(
    sink: SseSink,
    *,
    genesis_html: Path | None = None,
    stream_path: str = DEFAULT_ROUTE_PATH,
    channel: str = DEFAULT_CHANNEL,
    keepalive_seconds: float = 15.0,
) -> Starlette:
    """Build the minimal ephemeral bootstrap ASGI app.

    Registers the read-only ``provision.*`` SSE route on ``sink`` and, when
    ``genesis_html`` is given, serves that file at ``GET /``. No RBAC, no
    read-model, no mutating verb - Day-1 has none of those and the console is
    a read surface (``app-shape.instructions.md`` § Operator console).
    """
    routes: list[Route] = [
        make_provision_stream_route(
            sink=sink,
            channel=channel,
            path=stream_path,
            keepalive_seconds=keepalive_seconds,
            authorize=_anonymous_authorize,
        )
    ]
    if genesis_html is not None:
        routes.append(Route("/", _genesis_endpoint(genesis_html), methods=["GET"]))
    return Starlette(routes=routes)


async def stdin_byte_chunks(
    stream: BinaryIO | None = None,
    *,
    chunk_size: int = 65536,
) -> AsyncIterator[bytes]:
    """Yield chunks of a binary stream without blocking the event loop.

    ``sys.stdin.buffer`` reads are blocking, so each read is dispatched to the
    default executor. Injecting ``stream`` (e.g. an ``io.BytesIO``) makes the
    adapter testable.
    """
    source = stream if stream is not None else sys.stdin.buffer
    loop = asyncio.get_running_loop()
    while True:
        chunk = await loop.run_in_executor(None, source.read, chunk_size)
        if not chunk:
            break
        yield chunk


async def run_bootstrap(
    *,
    line_chunks: AsyncIterable[bytes | str],
    sink: SseSink,
    serve: Callable[[asyncio.Event], Coroutine[object, object, None]],
    bridge: TerraformProvisionBridge,
    linger_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run the server and the stdin pump together, then stop cleanly.

    ``serve`` receives a stop :class:`asyncio.Event` and MUST return once it is
    set. The pump publishes ``provision.*`` events onto ``sink`` (which
    ``serve`` fans out); after the apply ends and a short linger lets the
    browser render the finale, the stop event is set so the server exits.

    If the server task terminates before the pump does - port already bound,
    permission denied, uvicorn startup error - the pump is cancelled and the
    server's exception is re-raised immediately. Without this race the pump
    would drain the entire ``terraform apply`` (minutes) into a dead sink
    before the operator saw the error. A cancelled or errored pump propagates
    before the linger, and the ``finally`` still stops the server.
    """
    publisher = SseProvisionPublisher(sink=sink)
    stop = asyncio.Event()
    server_task: asyncio.Task[None] = asyncio.create_task(serve(stop))
    pump_task: asyncio.Task[None] = asyncio.create_task(
        pump_provision_events(aiter_json_lines(line_chunks), publisher, bridge=bridge)
    )
    try:
        await asyncio.wait({pump_task, server_task}, return_when=asyncio.FIRST_COMPLETED)
        if server_task.done() and not pump_task.done():
            pump_task.cancel()
            with suppress(asyncio.CancelledError):
                await pump_task
            await server_task  # re-raise startup error
        else:
            await pump_task  # propagate pump errors
            await sleep(linger_seconds)
    finally:
        stop.set()
        if not pump_task.done():
            pump_task.cancel()
            with suppress(asyncio.CancelledError):
                await pump_task
        with suppress(asyncio.CancelledError):
            await server_task


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fdai.delivery.provisioning",
        description="Ephemeral Day-1 Genesis bootstrap: pump 'terraform apply -json' "
        "(stdin) into a local provision.* SSE server.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port")
    parser.add_argument(
        "--genesis-html",
        default=None,
        help="path to the Genesis HTML to serve at '/'; omit to serve only the SSE route",
    )
    parser.add_argument(
        "--console-output-key",
        default=DEFAULT_CONSOLE_OUTPUT,
        help="Terraform output name carrying the operator-console URL",
    )
    parser.add_argument(
        "--waiting-threshold-seconds",
        type=float,
        default=DEFAULT_WAITING_THRESHOLD_SECONDS,
        help="elapsed seconds after which a slow resource becomes provision.waiting",
    )
    parser.add_argument(
        "--linger-seconds",
        type=float,
        default=DEFAULT_LINGER_SECONDS,
        help="seconds to keep serving after the apply ends so the finale renders",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint - wire stdin + a real uvicorn server, then run the pump."""
    import uvicorn

    args = _build_arg_parser().parse_args(argv)
    bridge = TerraformProvisionBridge(
        console_output_key=args.console_output_key,
        waiting_threshold_seconds=args.waiting_threshold_seconds,
    )
    sink: SseSink = InMemorySseSink()
    genesis = Path(args.genesis_html) if args.genesis_html else None
    app = build_bootstrap_app(sink, genesis_html=genesis)

    async def _serve(stop: asyncio.Event) -> None:
        config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve())
        await stop.wait()
        server.should_exit = True
        await serve_task

    asyncio.run(
        run_bootstrap(
            line_chunks=stdin_byte_chunks(),
            sink=sink,
            serve=_serve,
            bridge=bridge,
            linger_seconds=args.linger_seconds,
        )
    )
    return 0


__all__ = [
    "build_bootstrap_app",
    "main",
    "run_bootstrap",
    "stdin_byte_chunks",
]
