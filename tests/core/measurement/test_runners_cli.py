"""CLI wire-up tests for :mod:`aiopspilot.core.measurement.runners_cli`.

The CLI is the entry point the phase-4 Container Apps Jobs
(``infra/modules/measurement-runners/``) launch. These tests prove:

- Env-var mode selection (``baseline`` / ``growth`` / anything else).
- Fail-fast on invalid mode (exit ``2``) — matches the coding-conventions
  fail-fast rule.
- Successful run on both modes (exit ``0``) — upstream CLI is a health
  probe surface a fork extends by binding real seams; the shipped
  version MUST succeed so Terraform Job wire-up is provable.
- Unexpected exceptions in the runner body downgrade to exit ``3``, not
  ``0`` — a runtime crash pages an operator.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from aiopspilot.core.measurement import runners_cli
from aiopspilot.core.measurement.runners_cli import (
    _ENV_MODE,
    MeasurementMode,
    main,
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(_ENV_MODE, raising=False)
    yield


def test_missing_mode_env_returns_exit_2(clean_env: None) -> None:
    assert main() == 2


def test_invalid_mode_returns_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_MODE, "not-a-mode")
    assert main() == 2


def test_baseline_mode_returns_exit_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_MODE, "baseline")
    assert main() == 0


def test_growth_mode_returns_exit_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_MODE, "growth")
    assert main() == 0


def test_mode_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_MODE, "BASELINE")
    assert main() == 0
    monkeypatch.setenv(_ENV_MODE, "Growth")
    assert main() == 0


def test_baseline_exception_returns_exit_3(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> int:
        raise RuntimeError("simulated runner failure")

    monkeypatch.setenv(_ENV_MODE, "baseline")
    monkeypatch.setattr(runners_cli, "_run_baseline", _boom)
    assert main() == 3


def test_growth_exception_returns_exit_3(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> int:
        raise ValueError("simulated growth failure")

    monkeypatch.setenv(_ENV_MODE, "growth")
    monkeypatch.setattr(runners_cli, "_run_growth", _boom)
    assert main() == 3


def test_measurement_mode_enum_covers_both_terraform_values() -> None:
    """The infra module's Terraform ``AIOPSPILOT_MEASUREMENT_MODE`` env can only
    be ``baseline`` or ``growth`` — the CLI enum MUST match."""
    assert {m.value for m in MeasurementMode} == {"baseline", "growth"}
