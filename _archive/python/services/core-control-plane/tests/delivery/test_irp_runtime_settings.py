from __future__ import annotations

from typing import Any

from fdai.delivery.irp import RuntimeSettingsIrpEventHandler
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Handler:
    def __init__(self, budget: float, calls: list[tuple[float, dict[str, Any]]]) -> None:
        self._budget = budget
        self._calls = calls

    async def handle(self, payload: dict[str, Any]) -> None:
        self._calls.append((self._budget, payload))


async def test_skips_non_alert_without_reading_invalid_settings() -> None:
    settings = RuntimeSettingsService(
        store=InMemoryStateStore(),
        env={"FDAI_IRP_ENABLED": "invalid"},
    )
    calls: list[tuple[float, dict[str, Any]]] = []
    handler = RuntimeSettingsIrpEventHandler(
        settings=settings,
        handler_factory=lambda budget: _Handler(budget, calls),  # type: ignore[arg-type]
    )

    result = await handler.handle({"event_type": "inventory.updated"})

    assert result is None
    assert calls == []


async def test_applies_latest_enablement_and_budget() -> None:
    store = InMemoryStateStore()
    settings = RuntimeSettingsService(store=store, env={})
    calls: list[tuple[float, dict[str, Any]]] = []
    handler = RuntimeSettingsIrpEventHandler(
        settings=settings,
        handler_factory=lambda budget: _Handler(budget, calls),  # type: ignore[arg-type]
    )
    alert = {"event_type": "monitor.alert"}

    assert await handler.handle(alert) is None
    await settings.update(
        actor_id="owner-1",
        changes={"irp.enabled": True, "irp.budget_seconds": 42},
        expected_revision=0,
    )
    await handler.handle(alert)

    assert calls == [(42.0, alert)]
