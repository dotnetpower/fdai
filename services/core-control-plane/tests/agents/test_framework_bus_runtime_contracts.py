"""Round-one framework bus and runtime contract regressions."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import replace
from typing import Any

import pytest
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.kpi import KpiCollector, KpiEvidenceState
from fdai.agents._framework.pantheon import (
    LLM_HOT_PATH_ALLOWLIST,
    LLM_HOT_PATH_NAMES,
    LLM_OFF_PATH_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents._framework.registry import PantheonRegistry, PantheonRegistryError, load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.runtime_health import report_agent_kpis
from fdai.agents._framework.topics import partition_key_for
from fdai.agents.norns import Norns
from fdai.delivery.event_bus_multiplex import (
    MultiplexedEventBus,
    per_agent_multiplexed_consumer_group,
)
from fdai.shared.providers.local import LocalEventBus
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_service_contracts.semantic_turn import multiplexed_consumer_group


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _verdict_payload(correlation_id: str = "c", **extra: object) -> dict[str, object]:
    return {
        "correlation_id": correlation_id,
        "idempotency_key": f"verdict:{correlation_id}",
        **extra,
    }


def _spec(name: str) -> Any:
    return next(spec for spec in PANTHEON_SPECS if spec.name == name)


def test_multiplex_per_agent_mode_reads_physical_once_with_distinct_group() -> None:
    async def run() -> None:
        raw = InMemoryEventBus()
        bus = MultiplexedEventBus(
            bus=raw,
            logical_topics=frozenset({"object.event", "object.verdict"}),
            physical_topic="objects",
            per_agent_consumer_groups=True,
        )
        event_stream = bus.subscribe("object.event", "fdai-pantheon.Heimdall")
        verdict_stream = bus.subscribe("object.verdict", "fdai-pantheon.Heimdall")

        await bus.publish("object.event", "one", {"kind": "event"})
        await bus.publish("object.verdict", "two", {"kind": "verdict"})

        assert (await asyncio.wait_for(anext(event_stream), timeout=0.5)).payload["kind"] == "event"
        assert (await asyncio.wait_for(anext(verdict_stream), timeout=0.5)).payload[
            "kind"
        ] == "verdict"
        assert set(raw._offsets) == {
            ("objects", per_agent_multiplexed_consumer_group("fdai-pantheon.Heimdall"))
        }
        assert per_agent_multiplexed_consumer_group("g") != per_agent_multiplexed_consumer_group(
            "g.object.event"
        )
        assert per_agent_multiplexed_consumer_group("g") != multiplexed_consumer_group(
            "g", "object.event"
        )
        await event_stream.aclose()
        await verdict_stream.aclose()
        await bus.close()

    asyncio.run(run())


def test_inmemory_bus_validator_retry_duplicate_and_ordered_poison_halt() -> None:
    calls: list[int] = []

    def validator(_topic: str, payload: dict[str, Any]) -> None:
        if payload.get("bad"):
            raise ValueError("bad payload")

    async def flaky(_topic: str, _payload: dict[str, Any]) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")

    bus = InMemoryBus(
        registry=load_pantheon(),
        payload_validator=validator,
        handler_max_retries=1,
        duplicate_delivery_count=2,
    )
    bus.subscribe("object.verdict", "Thor", flaky)

    asyncio.run(bus.publish("Forseti", "object.verdict", _verdict_payload()))

    assert len(calls) == 3
    assert bus.handler_retries == 1
    assert bus.duplicate_deliveries == 1
    with pytest.raises(ValueError, match="bad payload"):
        asyncio.run(bus.publish("Forseti", "object.verdict", _verdict_payload("c2", bad=True)))
    assert bus.schema_violations == 1

    async def poison(_topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("poison")

    bus.subscribe("object.action-run", "Saga", poison)
    asyncio.run(
        bus.publish(
            "Thor",
            "object.action-run",
            {"correlation_id": "c3", "resource_id": "r1", "idempotency_key": "k1"},
        )
    )
    assert bus.ordered_poison_halts == 1
    with pytest.raises(RuntimeError, match="halted"):
        asyncio.run(
            bus.publish(
                "Thor",
                "object.action-run",
                {"correlation_id": "c4", "resource_id": "r1", "idempotency_key": "k2"},
            )
        )


def test_bridge_snapshot_reports_idle_consumer_delivery_count_and_time() -> None:
    async def run() -> dict[str, object]:
        provider = LocalEventBus()
        bridge = EventBusBridge(provider=provider, registry=load_pantheon())

        async def handler(_topic: str, _payload: dict[str, object]) -> None:
            return None

        bridge.subscribe("object.verdict", "Thor", handler)
        task = asyncio.create_task(bridge.run())
        await asyncio.sleep(0)
        idle_snapshot = bridge.snapshot()
        await bridge.publish("Forseti", "object.verdict", _verdict_payload())
        for _ in range(20):
            await asyncio.sleep(0)
            if bridge.snapshot()["consumer_deliveries"].get("Thor:object.verdict") == 1:
                break
        delivered_snapshot = bridge.snapshot()
        await bridge.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return {"idle": idle_snapshot, "delivered": delivered_snapshot}

    snapshots = asyncio.run(run())
    assert snapshots["idle"]["consumer_states"]["Thor:object.verdict"] == "idle"
    assert snapshots["delivered"]["consumer_deliveries"]["Thor:object.verdict"] == 1
    assert "Thor:object.verdict" in snapshots["delivered"]["consumer_last_delivery_at"]


async def test_local_event_bus_compacts_beyond_bound_without_dropping_unread_records() -> None:
    bus = LocalEventBus(max_records_per_topic=2)
    await bus.publish("object.event", "k1", {"n": 1})
    await bus.publish("object.event", "k2", {"n": 2})
    await bus.publish("object.event", "k3", {"n": 3})
    assert [payload["n"] for _key, payload in bus._records["object.event"]] == [2, 3]

    first = bus.subscribe("object.event", "known-a")
    second = bus.subscribe("object.event", "known-b")
    assert (await anext(first)).payload["n"] == 2
    await bus.publish("object.event", "k4", {"n": 4})
    assert [payload["n"] for _key, payload in bus._records["object.event"]] == [2, 3, 4]
    assert (await anext(second)).payload["n"] == 2
    first_next = asyncio.create_task(anext(first))
    second_next = asyncio.create_task(anext(second))
    await asyncio.sleep(0)
    assert (await asyncio.wait_for(first_next, timeout=0.5)).payload["n"] == 3
    assert (await asyncio.wait_for(second_next, timeout=0.5)).payload["n"] == 3
    assert [payload["n"] for _key, payload in bus._records["object.event"]] == [3, 4]
    await first.aclose()
    await second.aclose()


async def test_local_event_bus_keeps_replay_for_late_groups_within_bound() -> None:
    bus = LocalEventBus(max_records_per_topic=3)
    for value in (1, 2, 3):
        await bus.publish("object.event", f"k{value}", {"n": value})
    early = bus.subscribe("object.event", "early")
    for expected in (1, 2, 3):
        assert (await anext(early)).payload["n"] == expected

    late = bus.subscribe("object.event", "late")
    assert (await anext(late)).payload["n"] == 1
    await early.aclose()
    await late.aclose()


def test_registry_rejects_unknown_subscriptions_and_unregistered_owned_topics() -> None:
    with pytest.raises(PantheonRegistryError, match="subscribes unknown"):
        PantheonRegistry((replace(_spec("Odin"), subscribes=("object.nope",)),))
    with pytest.raises(PantheonRegistryError, match="not registered"):
        PantheonRegistry((replace(_spec("Odin"), owns=("NotARegisteredBusObject",)),))


def test_partition_key_uses_enforced_envelope_without_redundant_topic_branches() -> None:
    assert (
        partition_key_for("object.action-run", {"resource_id": "r", "correlation_id": "c"}) == "r"
    )
    assert partition_key_for("object.verdict", {"correlation_id": "c"}) == "c"
    assert partition_key_for("object.event", {"correlation_id": "c"}) == "c"


def test_rate_limiter_is_sliding_not_fixed_window() -> None:
    clock = _Clock()
    limiter = RateLimiter(per_minute=2, per_hour=100, now=clock.now)
    assert limiter.allow() is True
    clock.advance(59.9)
    assert limiter.allow() is True
    clock.advance(0.099)
    assert limiter.allow() is False
    clock.advance(59.901)
    assert limiter.allow() is True


def test_agent_rate_limit_queue_flushes_in_order_and_overflow_is_audited() -> None:
    async def run() -> tuple[list[str], list[tuple[str, str]], dict[str, int]]:
        clock = _Clock()
        bus = InMemoryBus(registry=load_pantheon())
        agent = Agent(_spec("Njord"))
        agent.bind_bus(bus)
        agent._proposal_limiter = RateLimiter(per_minute=1, per_hour=100, now=clock.now)
        agent._proposal_queue = deque(maxlen=1)
        audits: list[tuple[str, str]] = []

        async def audit(agent_name: str, topic: str, _payload: dict[str, Any]) -> None:
            audits.append((agent_name, topic))

        agent.bind_rate_limit_overflow_auditor(audit)
        payloads = [
            {"correlation_id": f"c{i}", "idempotency_key": f"k{i}", "resource_id": f"r{i}"}
            for i in range(3)
        ]
        assert await agent._publish_proposal("object.cost-anomaly", payloads[0]) is True
        assert await agent._publish_proposal("object.cost-anomaly", payloads[1]) is False
        assert await agent._publish_proposal("object.cost-anomaly", payloads[2]) is False
        clock.advance(60.0)
        assert await agent.flush_rate_limited_proposals() == 1
        return (
            [
                str(message.payload["correlation_id"])
                for message in bus.messages_on("object.cost-anomaly")
            ],
            audits,
            agent.behavior_snapshot(),
        )

    published, audits, behavior = asyncio.run(run())
    assert published == ["c0", "c1"]
    assert audits == [("Njord", "object.cost-anomaly")]
    assert behavior["rate_limit_queued"] == 1
    assert behavior["rate_limit_overflow"] == 1


def test_maintenance_tick_isolated_and_flushes_norns_without_blocking_consumers() -> None:
    async def run() -> tuple[int, dict[str, int]]:
        bus = InMemoryBus(registry=load_pantheon())
        gate_open = False
        norns = Norns(promotion_threshold=1)
        norns.bind_candidate_publication_gate(lambda: gate_open)
        norns.bind_bus(bus)
        await norns.on_typed_message(
            "object.issue",
            {
                "producer_principal": "Saga",
                "fingerprint": "fp-maint",
                "correlation_id": "fp-maint-1",
                "idempotency_key": "fp-maint-1",
            },
        )
        assert bus.messages_on("object.rule-candidate") == []
        gate_open = True
        await norns.maintenance_tick()
        return len(bus.messages_on("object.rule-candidate")), norns.behavior_snapshot()

    published_count, behavior = asyncio.run(run())
    assert published_count == 1
    assert behavior["maintenance_tick:candidates_flushed"] == 1


def test_kpi_report_uses_observed_behavior_values_and_not_observed_for_gaps() -> None:
    collector = KpiCollector()
    report_agent_kpis(
        collector,
        {
            "Saga": {
                "status": "stub",
                "behavior": {"maintenance_tick:audit_chain_verified": 1},
            }
        },
    )
    measured = collector.latest(agent="Saga", metric="audit_chain_integrity_rate")
    assert measured is not None
    assert measured.value == 1.0
    assert measured.evidence_state is KpiEvidenceState.MEASURED
    missing = collector.latest(agent="Saga", metric="replay_success_rate")
    assert missing is not None
    assert missing.value is None
    assert missing.evidence_state is KpiEvidenceState.NOT_OBSERVED


def test_thor_role_contract_carries_global_lifecycle_executor_role() -> None:
    thor = _spec("Thor")
    assert "executes=none;" in thor.role_contract()
    assert "lifecycle_roles=judge:Forseti,approver:Var,executor:Thor" in thor.role_contract()
    assert thor.role_contract() in thor.conversation.system_prompt


def test_hot_path_llm_names_exclude_off_path_norns_with_compatible_alias() -> None:
    assert LLM_HOT_PATH_NAMES == frozenset({"Bragi", "Forseti"})
    assert LLM_OFF_PATH_NAMES == frozenset({"Norns"})
    assert LLM_HOT_PATH_ALLOWLIST == LLM_HOT_PATH_NAMES
    assert "Norns" not in LLM_HOT_PATH_ALLOWLIST


def test_base_typed_handler_records_unhandled_counter() -> None:
    agent = Agent(_spec("Njord"))
    asyncio.run(agent.on_typed_message("object.event", {"correlation_id": "c"}))
    assert agent.behavior_snapshot()["typed_message:unhandled"] == 1


def test_runtime_observer_separates_shadow_action_run_success() -> None:
    runtime = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="raw")
    asyncio.run(
        runtime._observe_action_run(
            "object.action-run",
            {"state": "succeeded", "shadow_mode": True},
        )
    )
    asyncio.run(
        runtime._observe_action_run(
            "object.action-run",
            {"state": "succeeded", "shadow_mode": False},
        )
    )
    assert runtime.shadow_decisions["shadow_action_run:succeeded"] == 1
    assert runtime.shadow_decisions["action_run:succeeded"] == 1
