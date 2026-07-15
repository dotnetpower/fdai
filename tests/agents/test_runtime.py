"""Composition-root wiring tests for :class:`PantheonRuntime`.

These prove the seam that runs all 15 agents against a real
:class:`~fdai.shared.providers.event_bus.EventBus` provider: every
declared subscription is registered, publishing agents are bound to the
bridge, and a raw ingress event flows through Huginn into
``object.event`` (one hop over the provider). Multi-hop fan-out is
already covered by the sync-dispatch wave tests; the in-memory provider
snapshots its queue per ``subscribe`` call, so a single ``run`` pass
drains one hop.
"""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.provider_adapters import (
    StateStoreActionRunStore,
    StateStoreAuditChainAdapter,
)
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RAW_TOPIC = "fdai.events"


def _build() -> tuple[PantheonRuntime, InMemoryEventBus]:
    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC)
    return runtime, provider


def test_build_instantiates_all_fifteen_agents() -> None:
    runtime, _ = _build()
    assert len(runtime.agents) == 15
    assert set(runtime.agents) == {s.name for s in PANTHEON_SPECS}


def test_build_registers_every_declared_subscription_plus_ingress() -> None:
    runtime, _ = _build()
    expected = sum(len(s.subscribes) for s in PANTHEON_SPECS) + 1  # +1 raw ingress
    assert runtime.subscription_count == expected
    # The raw ingress topic and object.event both have subscribers.
    assert _RAW_TOPIC in runtime.bridge._subs
    assert "object.event" in runtime.bridge._subs


def test_object_event_fans_out_to_forseti_and_heimdall() -> None:
    runtime, _ = _build()
    subscribers = {name for name, _ in runtime.bridge._subs["object.event"]}
    assert {"Forseti", "Heimdall"} <= subscribers


async def test_runtime_injects_heimdall_incident_candidate_hook() -> None:
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> None:
        candidates.append(candidate)

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic=_RAW_TOPIC,
        incident_candidate_hook=capture,
    )
    heimdall = runtime.agents["Heimdall"]
    assert isinstance(heimdall, Heimdall)

    for index in range(5):
        await heimdall.on_typed_message(
            "object.event",
            {
                "resource_id": "vm-1",
                "event_type": "cpu_spike",
                "correlation_id": "corr-1",
                "idempotency_key": f"event-{index}",
            },
        )

    assert len(candidates) == 1
    assert candidates[0]["producer_principal"] == "Heimdall"


def test_publishing_agents_are_bound_to_the_bridge() -> None:
    runtime, _ = _build()
    for name in ("Huginn", "Heimdall", "Forseti", "Thor", "Var", "Vidar", "Odin"):
        assert isinstance(runtime.agents[name].bus, EventBusBridge)


def test_shadow_by_default_forces_thor_shadow() -> None:
    runtime, _ = _build()
    assert runtime.enforce is False
    thor = runtime.agents["Thor"]
    assert isinstance(thor, Thor)

    async def _dispatch() -> object:
        return await thor.dispatch_verdict(
            {
                "correlation_id": "c-shadow",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-shadow",
            }
        )

    run = asyncio.run(_dispatch())
    assert run.shadow_mode is True
    assert run.outcome == "shadow_success"


def test_enforce_true_disables_forced_shadow() -> None:
    provider = InMemoryEventBus()
    executed: list[str] = []

    async def executor(context: dict) -> bool:
        executed.append(context["run"].correlation_id)
        return True

    async def rollback_executor(_action_run: dict) -> str:
        return "rollback:test"

    state_store = InMemoryStateStore()

    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        enforce=True,
        saga=Saga(audit_chain=StateStoreAuditChainAdapter(store=state_store)),
        thor_executor=executor,
        thor_state_store=StateStoreActionRunStore(store=state_store),
        rollback_executors={"state_forward_only": rollback_executor},
    )
    assert runtime.enforce is True
    thor = runtime.agents["Thor"]
    assert isinstance(thor, Thor)

    async def _dispatch() -> object:
        return await thor.dispatch_verdict(
            {
                "correlation_id": "c-enforce",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-enforce",
            }
        )

    run = asyncio.run(_dispatch())
    assert run.shadow_mode is False
    assert executed == ["c-enforce"]


def test_build_rejects_empty_raw_event_topic() -> None:
    with pytest.raises(ValueError, match="raw_event_topic"):
        PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="")


def test_build_rejects_blank_raw_event_topic() -> None:
    with pytest.raises(ValueError, match="raw_event_topic"):
        PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="   ")


def test_custom_consumer_group_prefix_is_applied() -> None:
    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        consumer_group_prefix="acme-pantheon",
    )
    assert runtime.bridge.consumer_group_prefix == "acme-pantheon"


def test_disabled_agents_are_excluded_from_wiring() -> None:
    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        disabled_agents=frozenset({"Loki", "Njord"}),
    )
    assert "Loki" not in runtime.agents
    assert "Njord" not in runtime.agents
    assert len(runtime.agents) == 13
    assert runtime.disabled == frozenset({"Loki", "Njord"})
    assert runtime.health()["disabled"] == ["Loki", "Njord"]


def test_disabling_a_subscriber_removes_its_subscriptions() -> None:
    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        disabled_agents=frozenset({"Heimdall"}),
    )
    # Heimdall subscribed object.event; with it disabled, only Forseti
    # remains on that topic.
    subscribers = {name for name, _ in runtime.bridge._subs["object.event"]}
    assert "Heimdall" not in subscribers
    assert "Forseti" in subscribers


def test_cannot_disable_hard_dependency_agents() -> None:
    for name in ("Saga", "Vidar"):
        with pytest.raises(ValueError, match="hard-dependency"):
            PantheonRuntime.build(
                provider=InMemoryEventBus(),
                raw_event_topic=_RAW_TOPIC,
                disabled_agents=frozenset({name}),
            )


def test_cannot_disable_unknown_agent() -> None:
    with pytest.raises(ValueError, match="unknown agents"):
        PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic=_RAW_TOPIC,
            disabled_agents=frozenset({"Zeus"}),
        )


def test_disabling_huginn_idles_ingress(caplog: pytest.LogCaptureFixture) -> None:
    provider = InMemoryEventBus()
    with caplog.at_level("WARNING"):
        runtime = PantheonRuntime.build(
            provider=provider,
            raw_event_topic=_RAW_TOPIC,
            disabled_agents=frozenset({"Huginn"}),
        )
    assert "Huginn" not in runtime.agents
    assert _RAW_TOPIC not in runtime.bridge._subs  # no ingress wired
    assert any(r.message == "pantheon_ingress_disabled_no_huginn" for r in caplog.records)


def test_injected_saga_replaces_the_default() -> None:
    provider = InMemoryEventBus()
    custom = Saga()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC, saga=custom)
    assert runtime.agents["Saga"] is custom


@pytest.mark.parametrize(
    ("kwargs", "missing"),
    [
        ({}, "thor_executor"),
        ({"thor_executor": lambda _: None}, "thor_state_store"),
        (
            {
                "thor_executor": lambda _: None,
                "thor_state_store": StateStoreActionRunStore(store=InMemoryStateStore()),
            },
            "durable_saga",
        ),
        (
            {
                "thor_executor": lambda _: None,
                "thor_state_store": StateStoreActionRunStore(store=InMemoryStateStore()),
                "saga": Saga(audit_chain=StateStoreAuditChainAdapter(store=InMemoryStateStore())),
            },
            "rollback_executors",
        ),
    ],
)
def test_enforce_requires_explicit_safety_bindings(kwargs: dict, missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic=_RAW_TOPIC,
            enforce=True,
            **kwargs,
        )


def test_health_snapshot_reports_agents_mode_and_metrics() -> None:
    runtime, _ = _build()
    health = runtime.health()
    assert health["agents"] == 15
    assert health["enforce"] is False
    assert health["ingress_dropped"] == 0
    assert "metrics" in health
    assert "subscriptions" in health


def test_health_includes_per_agent_state() -> None:
    runtime, _ = _build()
    agent_health = runtime.health()["agent_health"]
    assert agent_health["Thor"]["shadow_forced"] is True
    assert agent_health["Thor"]["active_runs"] == 0
    assert agent_health["Huginn"]["dedup_capacity"] >= 1
    # Disabled agents drop out of the per-agent health map.
    partial = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic=_RAW_TOPIC,
        disabled_agents=frozenset({"Loki"}),
    )
    assert "Loki" not in partial.health()["agent_health"]


def test_raw_event_flows_through_huginn_to_object_event() -> None:
    runtime, provider = _build()

    async def _drive() -> list[dict]:
        # Seed a raw ingress event before run() so the consumer snapshot
        # includes it (in-memory provider polls a snapshot per subscribe).
        await provider.publish(
            _RAW_TOPIC,
            "vm-1",
            {
                "id": "evt-1",
                "correlation_id": "corr-1",
                "resource_id": "vm-1",
                "event_type": "public_network_enabled",
            },
        )
        run_task = asyncio.create_task(runtime.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

        collected: list[dict] = []
        async for env in provider.subscribe("object.event", "assert-group"):
            collected.append(dict(env.payload))
        return collected

    events = asyncio.run(_drive())
    assert len(events) == 1
    assert events[0]["producer_principal"] == "Huginn"
    assert events[0]["event_type"] == "public_network_enabled"


def test_object_event_produces_forseti_verdict_over_provider() -> None:
    runtime, provider = _build()

    async def _drive() -> list[dict]:
        # Seed an object.event directly (provider.publish skips the
        # single-writer check that only bridge.publish enforces). Forseti
        # drains it and publishes object.verdict via the bridge.
        await provider.publish(
            "object.event",
            "corr-2",
            {
                "producer_principal": "Huginn",
                "correlation_id": "corr-2",
                "resource_id": "sa-1",
                "event_type": "public_network_enabled",
            },
        )
        run_task = asyncio.create_task(runtime.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

        collected: list[dict] = []
        async for env in provider.subscribe("object.verdict", "assert-verdict"):
            collected.append(dict(env.payload))
        return collected

    verdicts = asyncio.run(_drive())
    assert len(verdicts) == 1
    assert verdicts[0]["producer_principal"] == "Forseti"
    assert verdicts[0]["action_type"] == "remediate.disable-public-access"
    assert verdicts[0]["risk_verdict"] == "auto"


def test_unkeyed_ingress_event_is_dropped_not_dead_lettered() -> None:
    runtime, provider = _build()

    async def _drive() -> list[dict]:
        # A raw event with no id / event_id / idempotency_key: Huginn
        # cannot key it. The shadow pantheon drops it (the P1 loop still
        # processes the same record) rather than flooding the DLQ.
        await provider.publish(_RAW_TOPIC, "", {"resource_id": "r-no-key"})
        run_task = asyncio.create_task(runtime.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

        dlq: list[dict] = []
        async for env in provider.subscribe(f"{_RAW_TOPIC}.dlq", "assert-dlq"):
            dlq.append(dict(env.payload))
        return dlq

    dlq = asyncio.run(_drive())
    assert dlq == []  # dropped, not dead-lettered
    assert runtime.health()["ingress_dropped"] == 1


def test_huginn_dedup_memory_is_bounded() -> None:
    huginn = Huginn(dedup_capacity=2)

    async def _drive() -> tuple[dict | None, dict | None]:
        await huginn.ingest({"id": "a"})
        await huginn.ingest({"id": "b"})
        await huginn.ingest({"id": "c"})  # capacity 2 -> evicts "a"
        # "a" was evicted, so it is treated as new again.
        rearrived = await huginn.ingest({"id": "a"})
        # "c" is still tracked, so it is deduped.
        duplicate = await huginn.ingest({"id": "c"})
        return rearrived, duplicate

    rearrived, duplicate = asyncio.run(_drive())
    assert rearrived is not None
    assert duplicate is None


def test_huginn_rejects_non_positive_dedup_capacity() -> None:
    with pytest.raises(ValueError, match="dedup_capacity"):
        Huginn(dedup_capacity=0)


def test_shadow_observer_counts_verdicts_and_action_runs() -> None:
    runtime, provider = _build()

    async def _drive() -> None:
        # A seeded 'auto' verdict is observed once, and Thor reacts to it
        # in shadow - producing the ActionRun lifecycle (verdicted ->
        # executing -> succeeded) which the observer also tallies. This
        # proves the observer captures the pantheon's full shadow decision
        # chain, the baseline "shadow before enforce" needs.
        await provider.publish(
            "object.verdict",
            "c1",
            {
                "risk_verdict": "auto",
                "action_type": "ops.restart-service",
                "correlation_id": "c1",
                "resource_id": "r1",
            },
        )
        run_task = asyncio.create_task(runtime.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    assert runtime.shadow_decisions["verdict:auto"] == 1
    assert runtime.shadow_decisions["action_run:succeeded"] >= 1
    assert runtime.shadow_decisions["action_run:verdicted"] == 1
    assert runtime.health()["shadow_decisions"]["verdict:auto"] == 1


def test_runtime_feeds_the_divergence_ledger() -> None:
    provider = InMemoryEventBus()
    ledger = ShadowDivergenceLedger()
    runtime = PantheonRuntime.build(
        provider=provider, raw_event_topic=_RAW_TOPIC, divergence=ledger
    )

    async def _drive() -> None:
        await provider.publish(
            "object.verdict",
            "c1",
            {
                "risk_verdict": "auto",
                "action_type": "ops.restart-service",
                "correlation_id": "c1",
                "resource_id": "r1",
            },
        )
        run_task = asyncio.create_task(runtime.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    assert ledger.pantheon_total >= 1
    assert runtime.health()["divergence"] is not None


def test_heartbeat_logs_health(caplog: pytest.LogCaptureFixture) -> None:
    runtime, _ = _build()

    async def _drive() -> None:
        hb = asyncio.create_task(runtime._heartbeat(0.001))
        await asyncio.sleep(0.02)
        hb.cancel()
        try:
            await hb
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    with caplog.at_level("INFO"):
        asyncio.run(_drive())
    assert any(r.message == "pantheon_heartbeat" for r in caplog.records)


def test_health_isolates_a_raising_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    # H6: one agent whose health() raises must not collapse the whole
    # snapshot (Heimdall's probe / the heartbeat depend on it).
    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC)
    name, agent = next(iter(runtime.agents.items()))

    def _boom() -> dict[str, object]:
        raise RuntimeError("probe down")

    monkeypatch.setattr(agent, "health", _boom)
    health = runtime.health()  # must not raise
    assert health["agent_health"][name]["status"] == "error"
