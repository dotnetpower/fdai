from __future__ import annotations

import subprocess
from typing import cast

import pytest
from tools import console


def test_local_operator_api_env_uses_azure_cli_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")
    monkeypatch.setenv("FDAI_OPERATOR_API_LOCAL_ENTRA", "1")

    env = console._local_operator_api_env()

    assert env["FDAI_OPERATOR_API_LOCAL_AZURE_CLI"] == "1"
    assert "FDAI_OPERATOR_API_DEV_MODE" not in env
    assert "FDAI_OPERATOR_API_LOCAL_ENTRA" not in env


def test_select_operator_api_port_reuses_compatible_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console, "_health_ok", lambda port, timeout: True)
    monkeypatch.setattr(console, "_operator_api_usable", lambda port: True)

    assert console._select_operator_api_port(8010) == (8010, True)


def test_select_operator_api_port_avoids_authenticated_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console, "_health_ok", lambda port, timeout: True)
    monkeypatch.setattr(console, "_operator_api_usable", lambda port: False)
    monkeypatch.setattr(console, "_available_loopback_port", lambda: 43123)

    assert console._select_operator_api_port(8010) == (43123, False)


def test_select_operator_api_port_starts_requested_port_when_unused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console, "_health_ok", lambda port, timeout: False)

    assert console._select_operator_api_port(8010) == (8010, False)


def test_operator_api_command_uses_independent_operator_service() -> None:
    command = console._operator_api_command(43123)
    rendered = " ".join(command)

    assert "fdai_operator_service.main:create_app" in rendered
    assert "services/operator-service/src" in rendered
    assert "FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1" in rendered
    assert "fdai.delivery.operator_api" not in rendered
    assert command[-1] == "43123"


class _ProcessStub:
    def __init__(self, *, running: bool, timeout_once: bool = False) -> None:
        self.running = running
        self.timeout_once = timeout_once
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self) -> int | None:
        return None if self.running else 3

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if timeout is not None and self.timeout_once:
            self.timeout_once = False
            raise subprocess.TimeoutExpired("operator-api", timeout)
        self.running = False
        return 0


def _process(stub: _ProcessStub) -> subprocess.Popen[bytes]:
    return cast(subprocess.Popen[bytes], stub)


def test_wait_for_operator_api_stops_when_child_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health = pytest.fail
    monkeypatch.setattr(console, "_health_ok", health)

    assert console._wait_for_operator_api(_process(_ProcessStub(running=False)), 8010, 45) is False


def test_terminate_process_escalates_and_reaps() -> None:
    stub = _ProcessStub(running=True, timeout_once=True)

    console._terminate_process(_process(stub))

    assert stub.terminated is True
    assert stub.killed is True
    assert stub.wait_calls == 2


def test_terminate_process_reaps_an_already_exited_child() -> None:
    stub = _ProcessStub(running=False)

    console._terminate_process(_process(stub))

    assert stub.terminated is False
    assert stub.wait_calls == 1
