"""Freyr recurring sampler and forecast-to-verdict regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.freyr_sampling import UtilizationSample
from fdai.agents._framework.loki_adversarial import ChaosScenarioCandidate
from fdai.agents._framework.loki_scheduling import ChaosScheduleConfig
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.loki import Loki
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.product_selection import governed_execution_selection

_RAW_TOPIC = "fdai.events.freyr-recurring-test"
_NOW = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)


class _Sampler:
    def __init__(
        self,
        samples: Sequence[UtilizationSample],
        *,
        expected_observed_at: datetime | None = _NOW,
    ) -> None:
        self.samples = tuple(samples)
        self.expected_observed_at = expected_observed_at
        self.calls = 0

    async def read_utilization_samples(
        self,
        *,
        limit: int,
        observed_at: datetime,
    ) -> Sequence[UtilizationSample]:
        self.calls += 1
        assert limit > 0
        if self.expected_observed_at is not None:
            assert observed_at == self.expected_observed_at
        return self.samples


class _ScenarioGenerator:
    async def generate_scenarios(self, _design_ref: str) -> Sequence[ChaosScenarioCandidate]:
        return ()


async def test_freyr_recurring_sampling_feeds_existing_forecast_path_to_shadow_verdict() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    sampler = _Sampler(
        (
            UtilizationSample(
                resource_id="resource-scale",
                utilization=0.92,
                correlation_id="corr-scale",
                observed_at=_NOW.isoformat(),
            ),
        )
    )
    freyr = Freyr(bus=bus, clock=lambda: _NOW, utilization_sampler=sampler)
    forseti = Forseti(
        bus=bus,
        governed_execution_selected=governed_execution_selection(True),
    )
    bus.subscribe("object.capacity-forecast", "Forseti", forseti.on_typed_message)

    await freyr.maintenance_tick()

    (forecast,) = (message.payload for message in bus.messages_on("object.capacity-forecast"))
    (verdict,) = (message.payload for message in bus.messages_on("object.verdict"))
    assert forecast["resource_id"] == "resource-scale"
    assert forecast["recommendation"] == "scale_up"
    assert forecast["action_arguments"]["target_resource_ref"] == "resource-scale"
    assert verdict["action_type"] == "ops.scale-out"
    assert verdict["risk_verdict"] == "hil"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
    assert verdict["source_mode"] == "shadow"
    assert sampler.calls == 1
    assert freyr.behavior_snapshot()["capacity_sampling:sampled"] == 1


async def test_freyr_default_profile_keeps_sampled_forecast_advisory() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    freyr = Freyr(
        bus=bus,
        clock=lambda: _NOW,
        utilization_sampler=_Sampler(
            (
                UtilizationSample(
                    resource_id="resource-advisory",
                    utilization=0.95,
                    correlation_id="corr-advisory",
                    observed_at=_NOW.isoformat(),
                ),
            )
        ),
    )
    forseti = Forseti(
        bus=bus,
        governed_execution_selected=governed_execution_selection(False),
    )
    bus.subscribe("object.capacity-forecast", "Forseti", forseti.on_typed_message)

    await freyr.maintenance_tick()

    (verdict,) = (message.payload for message in bus.messages_on("object.verdict"))
    assert verdict["action_type"] == ""
    assert verdict["risk_verdict"] == "hil"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
    assert verdict["reason"] == "governed_execution_unselected"


async def test_freyr_unbound_sampler_records_visible_noop_health() -> None:
    freyr = Freyr(clock=lambda: _NOW)

    await freyr.maintenance_tick()

    health = freyr.health()
    assert freyr.behavior_snapshot()["capacity_sampling:unbound"] == 1
    assert health["status"] == "degraded"
    assert health["ingress"]["recurring_sampling"] == "disabled"


def test_freyr_optional_sampler_unbound_does_not_degrade_bound_capacity_health() -> None:
    freyr = Freyr(
        graduation_controller=object(),
        state_store=InMemoryStateStore(),
    )

    health = freyr.health()

    assert health["status"] == "ok"
    assert health["ingress"]["recurring_sampling"] == "disabled"
    assert health["ingress"]["reason"] == "utilization_sampler_unbound"


def test_freyr_sampled_forecast_reaches_forseti_on_local_event_bus_runtime() -> None:
    provider = LocalEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        governed_execution_selected=True,
    )
    freyr = runtime.agents["Freyr"]
    assert isinstance(freyr, Freyr)
    freyr.bind_utilization_sampler(
        _Sampler(
            (
                UtilizationSample(
                    resource_id="resource-runtime",
                    utilization=0.91,
                    correlation_id="corr-runtime",
                    observed_at=_NOW.isoformat(),
                ),
            ),
            expected_observed_at=None,
        )
    )

    async def _drive() -> None:
        await freyr.maintenance_tick()
        await _run_until(
            runtime,
            lambda: bool(_published_payloads(provider, "object.verdict")),
        )

    asyncio.run(_drive())

    (verdict,) = _published_payloads(provider, "object.verdict")
    assert verdict["action_type"] == "ops.scale-out"
    assert verdict["risk_verdict"] == "hil"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"


def test_runtime_build_binds_optional_freyr_and_loki_specialist_ports() -> None:
    sampler = _Sampler((), expected_observed_at=None)
    schedule = ChaosScheduleConfig(
        schedule_id="runtime-bound-schedule",
        cadence=timedelta(hours=1),
        targets=("target-runtime",),
        causal_hypothesis_ref="hypothesis:runtime",
        refutation_query_ref="query:runtime",
        impact_envelope_id="impact:runtime",
        recovery_plan_id="recovery:runtime",
        dry_run_receipt="dry-run:runtime",
        start_at=_NOW,
    )
    generator = _ScenarioGenerator()
    corpus = (
        ChaosScheduleConfig(
            schedule_id="runtime-corpus",
            cadence=timedelta(hours=1),
            targets=("target-corpus",),
            causal_hypothesis_ref="hypothesis:corpus",
            refutation_query_ref="query:corpus",
            impact_envelope_id="impact:corpus",
            recovery_plan_id="recovery:corpus",
            dry_run_receipt="dry-run:corpus",
        ),
    )

    runtime = PantheonRuntime.build(
        provider=LocalEventBus(),
        raw_event_topic=_RAW_TOPIC,
        freyr_state_store=InMemoryStateStore(),
        freyr_utilization_sampler=sampler,
        loki_state_store=InMemoryStateStore(),
        loki_recurring_schedule=schedule,
        loki_scenario_generator=generator,
        loki_scenario_corpus=corpus,
    )

    freyr = runtime.agents["Freyr"]
    loki = runtime.agents["Loki"]
    assert isinstance(freyr, Freyr)
    assert isinstance(loki, Loki)
    assert freyr._utilization_sampler is sampler
    assert loki._recurring_schedule is schedule
    assert loki._scenario_generator is generator
    assert loki.health()["ingress"]["recurring_scheduler"] == "active"
    assert loki.health()["ingress"]["adversarial_generator"] == "bound"


async def _run_until(
    runtime: PantheonRuntime,
    predicate: Any,
    *,
    steps: int = 2000,
) -> None:
    run_task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _published_payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]
