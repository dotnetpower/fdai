from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest

from fdai.delivery.mcp import (
    ManagedMcpClient,
    ManagedMcpClientConfig,
    ManagedMcpUnavailableError,
    McpAvailability,
    McpCallResult,
)


class _Session:
    def __init__(self, *, tools: frozenset[str] = frozenset({"read"})) -> None:
        self.tools = tools
        self.list_calls = 0
        self.call_calls = 0
        self.fail_calls = False
        self.block_probe = False
        self.closed = False

    async def list_tools(self) -> frozenset[str]:
        self.list_calls += 1
        if self.block_probe:
            await asyncio.Event().wait()
        return self.tools

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> McpCallResult:
        del name, arguments, timeout_seconds
        self.call_calls += 1
        if self.fail_calls:
            raise RuntimeError("synthetic failure")
        return McpCallResult(structured_content={"ok": True})

    async def close(self) -> None:
        self.closed = True


def _client(session: _Session, **overrides: object) -> ManagedMcpClient:
    config = {
        "allowed_tools": frozenset({"read"}),
        "startup_timeout_seconds": 0.1,
        "health_interval_seconds": 5.0,
        "failure_threshold": 1,
        "reset_timeout_seconds": 30.0,
        **overrides,
    }
    return ManagedMcpClient(session=session, config=ManagedMcpClientConfig(**config))  # type: ignore[arg-type]


async def test_probe_timeout_marks_optional_provider_unavailable() -> None:
    session = _Session()
    session.block_probe = True
    client = _client(session)

    assert await client.probe() is False
    assert client.availability is McpAvailability.UNAVAILABLE
    assert client.reason == "probe_timed_out"


async def test_unavailable_call_fails_without_contacting_provider() -> None:
    session = _Session(tools=frozenset())
    client = _client(session)
    assert await client.probe() is False

    with pytest.raises(ManagedMcpUnavailableError):
        await client.call_tool("read", {})

    assert session.call_calls == 0


async def test_probe_requires_complete_allowlist() -> None:
    session = _Session(tools=frozenset({"other"}))
    client = _client(session)

    assert await client.probe() is False
    assert client.reason == "allowlisted_tools_missing"


async def test_failure_opens_circuit_and_later_calls_fail_fast() -> None:
    session = _Session()
    session.fail_calls = True
    client = _client(session)
    assert await client.probe() is True

    with pytest.raises(RuntimeError, match="synthetic failure"):
        await client.call_tool("read", {})
    with pytest.raises(ManagedMcpUnavailableError):
        await client.call_tool("read", {})

    assert session.call_calls == 1
    assert client.reason == "circuit_open"


async def test_probe_recovers_provider_after_failure() -> None:
    session = _Session(tools=frozenset())
    client = _client(session)
    assert await client.probe() is False
    session.tools = frozenset({"read"})

    assert await client.probe() is True
    assert client.availability is McpAvailability.AVAILABLE
    assert (await client.call_tool("read", {})).structured_content == {"ok": True}


async def test_close_stops_monitor_and_closes_session() -> None:
    session = _Session()
    client = _client(session)
    await client.start()
    await client.close()

    assert session.closed is True
