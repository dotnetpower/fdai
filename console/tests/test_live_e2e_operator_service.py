"""Isolation regressions for the authenticated Live E2E Operator launcher."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fdai_operator_service.environment import (
    DEFAULT_LIVE_STAGE_CONSUMER_GROUP,
    LIVE_STAGE_CONSUMER_GROUP_ENV,
)

SCRIPT = Path(__file__).parent / "live-e2e" / "operator_service.py"


def _load_launcher() -> object:
    spec = importlib.util.spec_from_file_location("fdai_live_e2e_operator_service", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Live E2E Operator launcher could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_e2e_operator_never_reuses_production_consumer_group(monkeypatch) -> None:
    launcher = _load_launcher()
    monkeypatch.setenv(LIVE_STAGE_CONSUMER_GROUP_ENV, DEFAULT_LIVE_STAGE_CONSUMER_GROUP)
    captured_environment: dict[str, str] = {}

    def create_app(environment, *, composition):
        del composition
        captured_environment.update(environment)
        return object()

    monkeypatch.setattr(launcher, "create_app", create_app)

    launcher.build_app()

    group_id = captured_environment[LIVE_STAGE_CONSUMER_GROUP_ENV]
    assert group_id != DEFAULT_LIVE_STAGE_CONSUMER_GROUP  # noqa: S101
    assert group_id.startswith(launcher.LIVE_E2E_CONSUMER_GROUP_PREFIX)  # noqa: S101
