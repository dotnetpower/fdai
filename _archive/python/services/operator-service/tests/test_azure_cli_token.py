"""Focused tests for bounded local Azure CLI credential acquisition."""

from __future__ import annotations

import asyncio

import pytest
from fdai_operator_service.adapters import azure_cli_token as token_module
from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError


class _HungProcess:
    returncode = 0

    def __init__(self) -> None:
        self.killed = False
        self.blocked = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        await self.blocked.wait()
        return b"unreachable", b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        await self.blocked.wait()
        return 0


async def test_azure_cli_token_timeout_kills_process_and_bounds_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _HungProcess()

    async def create_process(*args: object, **kwargs: object) -> _HungProcess:
        del args, kwargs
        return process

    monkeypatch.setattr(token_module.shutil, "which", lambda _name: "/usr/bin/az")
    monkeypatch.setattr(token_module.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(token_module, "AZURE_CLI_TOKEN_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(token_module, "AZURE_CLI_KILL_WAIT_SECONDS", 0.001)

    with pytest.raises(ConversationBoundaryError) as raised:
        await token_module.azure_cli_token("https://example.invalid/")

    assert raised.value.status_code == 503
    assert raised.value.code == "azure_cli_token_timeout"
    assert process.killed is True


async def test_azure_cli_token_rejects_missing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(token_module.shutil, "which", lambda _name: None)

    with pytest.raises(ConversationBoundaryError) as raised:
        await token_module.azure_cli_token("https://example.invalid/")

    assert raised.value.code == "azure_cli_unavailable"
