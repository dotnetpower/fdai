from __future__ import annotations

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
