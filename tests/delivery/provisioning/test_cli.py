"""Tests for :mod:`fdai.delivery.provisioning.cli` - the Day-1 bootstrap.

The uvicorn wiring in ``main`` is a thin, logic-free glue layer and is not
unit-tested; everything with behaviour - the app builder, the stdin adapter,
and the orchestration - is injectable and covered here.
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator

from starlette.testclient import TestClient

from fdai.delivery.provisioning.cli import (
    build_bootstrap_app,
    run_bootstrap,
    stdin_byte_chunks,
)
from fdai.delivery.provisioning.terraform_bridge import TerraformProvisionBridge
from fdai.delivery.read_api.streaming.provision_stream import DEFAULT_CHANNEL
from fdai.shared.providers.testing.sse import InMemorySseSink


def _apply_summary(add: int) -> str:
    return json.dumps({"type": "change_summary", "changes": {"add": add, "operation": "apply"}})


def _outputs(url: str) -> str:
    return json.dumps({"type": "outputs", "outputs": {"console_url": {"value": url}}})


class TestBuildBootstrapApp:
    def test_stream_route_is_get_only(self) -> None:
        app = build_bootstrap_app(InMemorySseSink())
        client = TestClient(app)
        assert client.post("/provision/stream").status_code == 405

    def test_no_root_route_without_genesis(self) -> None:
        app = build_bootstrap_app(InMemorySseSink(), genesis_html=None)
        paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
        assert "/provision/stream" in paths
        assert "/" not in paths

    def test_serves_genesis_html_at_root(self, tmp_path) -> None:
        html = tmp_path / "genesis.html"
        html.write_text("<html><body>genesis</body></html>", encoding="utf-8")
        app = build_bootstrap_app(InMemorySseSink(), genesis_html=html)
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "genesis" in resp.text


class TestStdinByteChunks:
    async def test_reads_binary_stream_to_exhaustion(self) -> None:
        stream = io.BytesIO(b"line-1\nline-2\n")
        chunks = [chunk async for chunk in stdin_byte_chunks(stream, chunk_size=4)]
        assert b"".join(chunks) == b"line-1\nline-2\n"

    async def test_empty_stream_yields_nothing(self) -> None:
        chunks = [chunk async for chunk in stdin_byte_chunks(io.BytesIO(b""))]
        assert chunks == []


class TestRunBootstrap:
    async def test_pumps_events_and_stops_server(self) -> None:
        sink = InMemorySseSink()
        served = {"started": False, "stopped": False}

        async def _fake_serve(stop: asyncio.Event) -> None:
            served["started"] = True
            await stop.wait()
            served["stopped"] = True

        received: list[dict[str, object]] = []

        async def _subscriber() -> None:
            async for event in sink.subscribe(DEFAULT_CHANNEL):
                received.append(json.loads(event.data))
                if received[-1].get("type") == "provision.done":
                    break

        task = asyncio.create_task(_subscriber())
        await asyncio.sleep(0)  # let the subscriber attach before publishing

        async def _lines() -> AsyncIterator[bytes]:
            yield (_apply_summary(1) + "\n").encode()
            yield (_outputs("https://c.example.com") + "\n").encode()

        await run_bootstrap(
            line_chunks=_lines(),
            sink=sink,
            serve=_fake_serve,
            bridge=TerraformProvisionBridge(),
            linger_seconds=0.0,
        )

        await asyncio.wait_for(task, timeout=1.0)
        assert served["started"] and served["stopped"]
        assert [e["type"] for e in received] == ["provision.done"]
        assert received[-1]["console_url"] == "https://c.example.com"

    async def test_server_stopped_even_when_pump_errors(self) -> None:
        sink = InMemorySseSink()
        stopped = asyncio.Event()

        async def _fake_serve(stop: asyncio.Event) -> None:
            await stop.wait()
            stopped.set()

        async def _boom() -> AsyncIterator[bytes]:
            yield (_apply_summary(1) + "\n").encode()
            raise RuntimeError("terraform crashed")

        try:
            await run_bootstrap(
                line_chunks=_boom(),
                sink=sink,
                serve=_fake_serve,
                bridge=TerraformProvisionBridge(),
                linger_seconds=0.0,
            )
        except RuntimeError:
            pass

        await asyncio.wait_for(stopped.wait(), timeout=1.0)
        assert stopped.is_set()

    async def test_server_startup_failure_propagates_without_draining_pump(
        self,
    ) -> None:
        """A dead server (e.g. port already bound) fails fast, not after apply."""
        sink = InMemorySseSink()
        pump_pulled = asyncio.Event()

        async def _serve_crashes_on_startup(_stop: asyncio.Event) -> None:
            raise OSError("port already in use")

        async def _slow_lines() -> AsyncIterator[bytes]:
            # First line pulled → mark it, then hang forever. If run_bootstrap
            # did not race the pump against the server, it would sit here
            # for the full duration of an apply before noticing the dead server.
            yield (_apply_summary(1) + "\n").encode()
            pump_pulled.set()
            await asyncio.sleep(3600)
            yield b""

        raised: BaseException | None = None
        try:
            await asyncio.wait_for(
                run_bootstrap(
                    line_chunks=_slow_lines(),
                    sink=sink,
                    serve=_serve_crashes_on_startup,
                    bridge=TerraformProvisionBridge(),
                    linger_seconds=10.0,  # deliberately large; must not be waited
                ),
                timeout=1.0,
            )
        except OSError as exc:
            raised = exc

        assert isinstance(raised, OSError)
        assert "port already in use" in str(raised)
