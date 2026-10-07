from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fdai.agents import ForsetiBaselineScheduler
from fdai.agents.forseti import Forseti
from fdai.runtime.baseline_evaluation import (
    BASELINE_EVALUATION_ENABLED_ENV,
    BASELINE_EVALUATION_INTERVAL_ENV,
    bind_forseti_baseline_worker,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Ledger:
    async def current_generation(self) -> None:
        return None


class _Runtime:
    async def rule_generation_snapshot(self) -> Any:  # pragma: no cover - never awaited here
        raise AssertionError("binding MUST NOT read the rule generation")


def _bind(**overrides: Any) -> tuple[ForsetiBaselineScheduler | None, Forseti]:
    store = InMemoryStateStore()
    forseti = Forseti(state_store=store)
    values: dict[str, Any] = {
        "pantheon": SimpleNamespace(agents={"Forseti": forseti}),
        "state_store": store,
        "runtime": _Runtime(),
        "environment": {"FDAI_INVENTORY_DSN": "postgresql://localhost/inventory"},
    }
    values.update(overrides)
    scheduler = bind_forseti_baseline_worker(
        values["pantheon"],
        values["state_store"],
        values["runtime"],
        values["environment"],
        activation_ledger=_Ledger(),
    )
    return scheduler, forseti


def test_binds_scheduler_to_forseti_when_inputs_exist() -> None:
    scheduler, forseti = _bind()

    assert scheduler is not None
    assert forseti._baseline_scheduler is scheduler  # noqa: SLF001


@pytest.mark.parametrize(
    "overrides",
    [
        {"environment": {}},
        {"environment": {"FDAI_INVENTORY_DSN": "  "}},
        {"state_store": None},
        {"pantheon": None},
        {"pantheon": SimpleNamespace(agents={})},
        {
            "environment": {
                "FDAI_INVENTORY_DSN": "postgresql://localhost/inventory",
                BASELINE_EVALUATION_ENABLED_ENV: "false",
            }
        },
    ],
)
def test_missing_inputs_or_disabled_binds_nothing(overrides: dict[str, Any]) -> None:
    scheduler, forseti = _bind(**overrides)

    assert scheduler is None
    assert forseti._baseline_scheduler is None  # noqa: SLF001


def test_invalid_interval_fails_startup() -> None:
    with pytest.raises(RuntimeError, match="positive integer"):
        _bind(
            environment={
                "FDAI_STATE_STORE_DSN": "postgresql://localhost/state",
                BASELINE_EVALUATION_INTERVAL_ENV: "0",
            }
        )
