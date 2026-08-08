"""Measurement composition-root CLI tests."""

from __future__ import annotations

import pytest
from fdai.delivery import measurement_runner_cli


def test_invalid_mode_returns_two() -> None:
    assert measurement_runner_cli.main(["invalid"]) == 2


def test_baseline_missing_required_env_returns_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_SCENARIO_SET_VERSION", raising=False)
    assert measurement_runner_cli.main(["baseline"]) == 3


def test_baseline_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_baseline", _success)
    assert measurement_runner_cli.main(["baseline"]) == 0


def test_growth_unwired_fails_nonzero() -> None:
    assert measurement_runner_cli.main(["growth"]) == 3


def test_growth_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_growth", _success)
    assert measurement_runner_cli.main(["growth"]) == 0
