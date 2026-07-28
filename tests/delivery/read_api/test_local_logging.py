from __future__ import annotations

import logging

import pytest
from starlette.applications import Starlette

from fdai.delivery.read_api.dev import local as _local


@pytest.mark.parametrize(
    ("configured", "expected"),
    (("DEBUG", logging.DEBUG), ("unsupported", logging.INFO)),
)
def test_server_logging_honors_level_and_quiets_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
    expected: int,
) -> None:
    configured_levels: list[int] = []
    dependency_levels: dict[str, int] = {}
    monkeypatch.setattr(
        _local,
        "configure_logging",
        lambda *, level: configured_levels.append(level),
    )
    for logger_name in ("aiokafka", "httpx", "weasyprint"):
        monkeypatch.setattr(
            logging.getLogger(logger_name),
            "setLevel",
            lambda level, name=logger_name: dependency_levels.__setitem__(name, level),
        )

    _local._configure_server_logging({"FDAI_LOG_LEVEL": configured})

    assert configured_levels == [expected]
    assert dependency_levels == {
        "aiokafka": logging.WARNING,
        "httpx": logging.WARNING,
        "weasyprint": logging.WARNING,
    }


def test_server_app_configures_logging_before_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    application = Starlette()
    monkeypatch.setattr(
        _local,
        "_configure_server_logging",
        lambda: calls.append("logging"),
    )
    monkeypatch.setattr(
        _local,
        "app",
        lambda: calls.append("app") or application,
    )

    assert _local.server_app() is application
    assert calls == ["logging", "app"]
