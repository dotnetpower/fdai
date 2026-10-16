from __future__ import annotations

import logging
from typing import Any, cast

import fdai.composition as composition
from fdai.composition import environment_factory
from fdai.shared.config.models import AppConfig
from fdai.shared.telemetry import setup as telemetry_setup


def test_default_container_from_env_uses_injected_snapshot(monkeypatch: Any) -> None:
    environment = {"FDAI_LOG_LEVEL": "debug", "FDAI_EXAMPLE": "value"}
    config = cast(AppConfig, object())
    container = object()
    observed: dict[str, object] = {}

    class Provider:
        def __init__(self, actual: object) -> None:
            observed["environment"] = actual

        def get(self) -> AppConfig:
            return config

    def configure(actual: AppConfig, *, level: int) -> None:
        observed["telemetry"] = (actual, level)

    monkeypatch.setattr(environment_factory, "EnvVarConfigProvider", Provider)
    monkeypatch.setattr(composition, "default_container", lambda actual: container)
    monkeypatch.setattr(telemetry_setup, "configure_telemetry", configure)

    assert composition.default_container_from_env(environment) is container
    assert observed == {
        "environment": environment,
        "telemetry": (config, logging.DEBUG),
    }
