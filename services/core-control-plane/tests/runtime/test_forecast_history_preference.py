from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.runtime_settings import (
    RuntimeSettingsConflictError,
    RuntimeSettingsService,
    RuntimeSettingsUnavailableError,
)
from fdai.runtime.forecast_history_preference import (
    FORECAST_HISTORY_COLLECTION_KEY,
    PreferenceGatedForecastHistoryCollector,
)
from fdai.runtime.forecast_learning import forecast_history_collector_from_environment
from fdai.shared.providers.forecast_context import (
    ForecastContextRequest,
    ForecastContextUnavailableError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.test_forecast_history_sources import _configuration


def request() -> ForecastContextRequest:
    now = datetime(2026, 10, 19, tzinfo=UTC)
    return ForecastContextRequest(
        "a" * 64, "b" * 64, now - timedelta(hours=1), now - timedelta(minutes=5), now
    )


def _environment() -> dict[str, str]:
    bindings, producers = _configuration()
    return {
        "FDAI_STATE_STORE_DSN": "configured",
        "FDAI_FORECAST_TARGETS_JSON": '[{"target_kind":"capacity"}]',
        "FDAI_FORECAST_HISTORY_SOURCES_JSON": json.dumps(bindings),
        "FDAI_FORECAST_HISTORY_PRODUCERS_JSON": json.dumps(producers),
        "FDAI_FORECAST_HISTORY_COLLECTION_ENABLED": "true",
        "forecast.history_collection.enabled": "true",
    }


class Collector:
    def __init__(self, during_collect: Callable[[], Awaitable[None]] | None = None) -> None:
        self.calls = 0
        self.during_collect = during_collect

    async def collect(self, query: ForecastContextRequest) -> dict[str, Any]:
        assert query == request()
        self.calls += 1
        if self.during_collect is not None:
            await self.during_collect()
        return {"actions": [{"evidence_ref": "retained-history"}]}


def _settings(store: InMemoryStateStore | None = None, **kwargs: Any) -> RuntimeSettingsService:
    return RuntimeSettingsService(
        store=store if store is not None else InMemoryStateStore(),
        env=_environment(),
        durable=True,
        **kwargs,
    )


async def _enable(settings: RuntimeSettingsService, revision: int = 0) -> None:
    await settings.update(
        actor_id="owner-example",
        changes={FORECAST_HISTORY_COLLECTION_KEY: True},
        expected_revision=revision,
    )


async def test_deployment_variables_cannot_enable_collection_or_producer_io() -> None:
    settings = _settings()
    source = Collector()
    collector = PreferenceGatedForecastHistoryCollector(collector=source, settings=settings)

    with pytest.raises(ForecastContextUnavailableError, match="disabled"):
        await collector.collect(request())
    assert source.calls == 0
    projection = await settings.projection(can_manage=False)
    row = next(item for item in projection["integrations"] if item["key"] == "forecast-history")
    assert row["enabled"] is False
    assert row["enabled_source"] == "durable_settings"
    assert row["scoring_authority"] is False
    assert row["execution_authority"] is False


async def test_audited_preference_survives_restart_and_requires_no_recomposition() -> None:
    store = InMemoryStateStore()
    settings = _settings(store)
    source = Collector()
    collector = PreferenceGatedForecastHistoryCollector(collector=source, settings=settings)
    with pytest.raises(ForecastContextUnavailableError, match="disabled"):
        await collector.collect(request())
    await _enable(settings)
    assert await collector.collect(request()) == {"actions": [{"evidence_ref": "retained-history"}]}
    restarted = _settings(store)
    assert await restarted.forecast_history_collection_preference() == (True, 1)
    assert len(tuple(store.audit_entries)) == 1
    projection = await restarted.projection(can_manage=True)
    row = next(item for item in projection["integrations"] if item["key"] == "forecast-history")
    assert row["enabled"] is True and row["mode"] == "shadow"
    assert row["available"] is False and row["ready"] is False
    with pytest.raises(RuntimeSettingsConflictError):
        await _enable(restarted)


@pytest.mark.parametrize("reenable", [False, True])
async def test_preference_change_during_collection_discards_result(reenable: bool) -> None:
    settings = _settings()
    await _enable(settings)

    async def disable() -> None:
        await settings.update(
            actor_id="owner-example",
            changes={FORECAST_HISTORY_COLLECTION_KEY: False},
            expected_revision=1,
        )
        if reenable:
            await _enable(settings, revision=2)

    source = Collector(disable)
    collector = PreferenceGatedForecastHistoryCollector(collector=source, settings=settings)
    with pytest.raises(ForecastContextUnavailableError, match="preference changed"):
        await collector.collect(request())
    assert source.calls == 1


async def test_preference_disable_blocks_next_collection_without_restart() -> None:
    settings = _settings()
    await _enable(settings)
    source = Collector()
    collector = PreferenceGatedForecastHistoryCollector(collector=source, settings=settings)
    assert await collector.collect(request())
    await settings.update(
        actor_id="owner-example",
        changes={FORECAST_HISTORY_COLLECTION_KEY: False},
        expected_revision=1,
    )
    with pytest.raises(ForecastContextUnavailableError, match="disabled"):
        await collector.collect(request())
    assert source.calls == 1


@pytest.mark.parametrize("value", ["true", 1, {}, []])
async def test_preference_rejects_non_boolean_values(value: object) -> None:
    settings = _settings()
    with pytest.raises(ValueError, match="boolean"):
        await settings.update(
            actor_id="owner-example",
            changes={FORECAST_HISTORY_COLLECTION_KEY: value},
            expected_revision=0,
        )


async def test_enabling_without_source_prerequisites_is_explicitly_rejected() -> None:
    settings = RuntimeSettingsService(store=InMemoryStateStore(), env={}, durable=True)
    with pytest.raises(ValueError, match="prerequisites"):
        await _enable(settings)
    projection = await settings.projection(can_manage=False)
    row = next(
        item for item in projection["settings"] if item["key"] == FORECAST_HISTORY_COLLECTION_KEY
    )
    assert row["available"] is False
    assert row["unavailable_reason"]


async def test_composition_always_gates_environment_bound_collector() -> None:
    env = _environment()
    collector = forecast_history_collector_from_environment(
        dsn="configured", environment=env, runtime_settings=_settings()
    )
    assert isinstance(collector, PreferenceGatedForecastHistoryCollector)
    with pytest.raises(ForecastContextUnavailableError, match="disabled"):
        await collector.collect(request())


async def test_missing_durable_settings_refuses_collection() -> None:
    settings = RuntimeSettingsService(store=None, env=_environment())
    source = Collector()
    collector = PreferenceGatedForecastHistoryCollector(collector=source, settings=settings)
    with pytest.raises(RuntimeSettingsUnavailableError, match="durable"):
        await collector.collect(request())
    assert source.calls == 0


@pytest.mark.parametrize("failure", [RuntimeError("source unavailable"), asyncio.CancelledError()])
async def test_source_failure_or_cancellation_propagates(failure: BaseException) -> None:
    settings = _settings()
    await _enable(settings)

    async def fail() -> None:
        raise failure

    collector = PreferenceGatedForecastHistoryCollector(
        collector=Collector(fail), settings=settings
    )
    with pytest.raises(type(failure)):
        await collector.collect(request())


async def test_settings_read_failure_during_collection_never_returns_evidence() -> None:
    store = InMemoryStateStore()
    settings = _settings(store)
    await _enable(settings)

    async def corrupt() -> None:
        await store.write_state(
            "runtime-settings:policy",
            {"revision": 2, "overrides": {FORECAST_HISTORY_COLLECTION_KEY: "true"}},
        )

    collector = PreferenceGatedForecastHistoryCollector(
        collector=Collector(corrupt), settings=settings
    )
    with pytest.raises(RuntimeSettingsUnavailableError, match="stored runtime settings"):
        await collector.collect(request())
