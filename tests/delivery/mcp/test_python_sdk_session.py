from __future__ import annotations

import asyncio

import pytest

from fdai.delivery.mcp import PythonSdkMcpSession


class _Group:
    instances: list[_Group] = []
    hang_on_exit = False

    def __init__(self) -> None:
        self.tools = {"compute": object()}
        self.exit_calls = 0
        self.__class__.instances.append(self)

    async def __aenter__(self) -> _Group:
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exit_calls += 1
        if self.hang_on_exit:
            await asyncio.Event().wait()

    async def connect_to_server(self, *_args: object) -> None:
        await asyncio.sleep(0)


async def test_concurrent_discovery_initializes_one_sdk_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.client import session_group

    _Group.instances = []
    _Group.hang_on_exit = False
    monkeypatch.setattr(session_group, "ClientSessionGroup", _Group)
    session = PythonSdkMcpSession.stdio(
        command="azmcp",
        args=("server", "start"),
        read_timeout_seconds=1,
    )

    first, second = await asyncio.gather(session.list_tools(), session.list_tools())
    await session.close()

    assert first == second == frozenset({"compute"})
    assert len(_Group.instances) == 1
    assert _Group.instances[0].exit_calls == 1


async def test_hung_sdk_group_close_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp.client import session_group

    _Group.instances = []
    _Group.hang_on_exit = True
    monkeypatch.setattr(session_group, "ClientSessionGroup", _Group)
    session = PythonSdkMcpSession.stdio(
        command="azmcp",
        args=("server", "start"),
        read_timeout_seconds=1,
        close_timeout_seconds=0.1,
    )
    await session.list_tools()

    with pytest.raises(TimeoutError):
        await session.close()

    assert _Group.instances[0].exit_calls == 1
