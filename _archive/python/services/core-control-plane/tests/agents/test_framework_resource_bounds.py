"""Resource-bound regressions for shared Pantheon framework helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import DEFAULT_REDRIVE_BATCH_SIZE, EventBusBridge
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.execution_safety import maintain_agents
from fdai.agents._framework.introspection import mentioned
from fdai.agents._framework.ontology_index import (
    ContextIndexMessage,
    ContextIndexWorkerBindings,
    owned_context_index_handler,
)
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.tool_planner import ConversationToolPlan
from fdai.agents._framework.tool_prefetch import gather_tools
from fdai.agents.muninn import Muninn
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _envelope(index: int) -> dict[str, str]:
    return {"correlation_id": f"corr-{index}", "idempotency_key": f"event:corr-{index}"}


async def test_inmemory_bus_history_dead_letters_and_topic_index_are_bounded() -> None:
    bus = InMemoryBus(registry=load_pantheon(), history_limit=25, dead_letter_limit=7)

    async def boom(_topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("poison")

    bus.subscribe("object.event", "Heimdall", boom)
    for index in range(10_000):
        await bus.publish("Huginn", "object.event", _envelope(index))

    assert len(bus.published) == 25
    assert len(bus.messages_on("object.event")) == 25
    assert bus.messages_on("object.event")[0].payload["correlation_id"] == "corr-9975"
    assert len(bus.dead_letters) == 7
    assert bus.history_overflows == 9_975
    assert bus.dead_letter_overflows == 9_993


async def test_inmemory_bus_uses_one_snapshot_with_copy_on_write_subscriber_views() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    seen: list[tuple[bool, object]] = []

    async def first(_topic: str, payload: dict[str, Any]) -> None:
        payload["local"] = "mutated"
        seen.append(("local" in payload, payload["nested"]))

    async def second(_topic: str, payload: dict[str, Any]) -> None:
        seen.append(("local" in payload, payload["nested"]))

    bus.subscribe("object.event", "Heimdall", first)
    bus.subscribe("object.event", "Forseti", second)
    nested = {"items": list(range(1000))}
    await bus.publish("Huginn", "object.event", {**_envelope(1), "nested": nested})

    assert seen == [(True, nested), (False, nested)]
    assert bus.published[0].payload["nested"] == nested
    assert bus.published[0].payload["nested"] is not nested


async def test_inmemory_bus_isolates_nested_subscriber_mutation_from_history_and_siblings() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    seen: list[dict[str, Any]] = []

    async def mutating(_topic: str, payload: dict[str, Any]) -> None:
        payload["nested"]["items"].append("mutated")
        payload["nested"]["meta"]["owner"] = "first"

    async def observing(_topic: str, payload: dict[str, Any]) -> None:
        seen.append(payload["nested"])

    bus.subscribe("object.event", "Heimdall", mutating)
    bus.subscribe("object.event", "Forseti", observing)

    original = {"items": ["original"], "meta": {"owner": "source"}}
    await bus.publish("Huginn", "object.event", {**_envelope(2), "nested": original})

    assert original == {"items": ["original"], "meta": {"owner": "source"}}
    assert seen == [{"items": ["original"], "meta": {"owner": "source"}}]
    assert bus.published[0].payload["nested"] == {
        "items": ["original"],
        "meta": {"owner": "source"},
    }


async def test_redrive_uses_bounded_default_batch() -> None:
    provider = InMemoryEventBus(max_records_per_topic=20_000)
    bridge = EventBusBridge(provider=provider, registry=load_pantheon())
    seen: list[str] = []

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        seen.append(str(payload["correlation_id"]))

    for index in range(DEFAULT_REDRIVE_BATCH_SIZE + 5):
        await provider.dead_letter(
            "object.verdict",
            f"corr-{index}",
            {
                "correlation_id": f"corr-{index}",
                "idempotency_key": f"verdict:corr-{index}",
                "producer_principal": "Forseti",
            },
            reason="seed",
        )

    result = await bridge.redrive("object.verdict", handler)

    assert result == {"redriven": DEFAULT_REDRIVE_BATCH_SIZE, "failed": 0}
    assert len(seen) == DEFAULT_REDRIVE_BATCH_SIZE


async def test_maintenance_coalesces_stuck_shielded_ticks() -> None:
    class StuckAgent(Agent):
        async def maintenance_tick(self) -> None:
            await asyncio.Event().wait()

    agent = StuckAgent(load_pantheon().get("Heimdall"))
    task = asyncio.create_task(
        maintain_agents({"Heimdall": agent}, 0.001, tick_timeout=0.001, max_in_flight=1)
    )
    try:
        await asyncio.sleep(0.03)
        maintenance_tasks = [
            item
            for item in asyncio.all_tasks()
            if item.get_name() == "pantheon-maintenance.Heimdall.maintenance_tick"
        ]
        assert len(maintenance_tasks) == 1
        assert agent.behavior_snapshot()["maintenance_tick:skipped_in_flight"] > 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_rate_limiter_open_reservations_use_heap_bookkeeping() -> None:
    limiter = RateLimiter(per_minute=20_000, per_hour=20_000, now=lambda: 0.0)
    reservations = [await limiter.reserve() for _ in range(10_000)]

    assert all(reservation is not None for reservation in reservations)
    assert len(limiter._reservations) == 10_000
    assert len(limiter._reservation_minute_heap) == 10_000
    assert await limiter.reserve() is not None


async def test_durable_rate_limiter_stores_compact_buckets() -> None:
    store = InMemoryStateStore()
    limiter = RateLimiter(
        per_minute=20_000,
        per_hour=20_000,
        now=lambda: 12.4,
        state_store=store,
        scope="resource-bound-test",
    )

    for _ in range(500):
        reservation = await limiter.reserve()
        assert reservation is not None
        await reservation.commit()

    record = await store.read_state("pantheon/proposal-rate-limit/resource-bound-test")
    assert isinstance(record, Mapping)
    assert record["minute_buckets"] == {"12": 500}
    assert record["hour_buckets"] == {"12": 500}
    assert "minute_events" not in record
    assert "hour_events" not in record


async def test_tool_prefetch_runs_independent_tools_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.agents._framework import tool_prefetch

    monkeypatch.setattr(tool_prefetch, "PREFETCH_BUDGET_SECONDS", 1.0)
    starts: list[str] = []

    class Registry:
        async def invoke(
            self, *, agent_name: str, tool_id: str, question: str, trace_ref: str
        ) -> str:
            del agent_name, question, trace_ref
            starts.append(tool_id)
            await asyncio.sleep(0.05)
            return tool_id

    class Semantic:
        async def plan(
            self, question: str, *, agents: list[str], limit: int
        ) -> tuple[ConversationToolPlan, ...]:
            del question, agents, limit
            return (
                ConversationToolPlan(
                    agent="Bragi",
                    tool_id="list_agent_capabilities",
                    score=0.9,
                    matched_terms=(),
                ),
                ConversationToolPlan(
                    agent="Bragi",
                    tool_id="read_routing_policy",
                    score=0.8,
                    matched_terms=(),
                ),
                ConversationToolPlan(
                    agent="Thor",
                    tool_id="read_action_runs",
                    score=0.7,
                    matched_terms=(),
                ),
            )

    before = asyncio.get_running_loop().time()
    result = await gather_tools(
        "question",
        registry=Registry(),  # type: ignore[arg-type]
        semantic=Semantic(),  # type: ignore[arg-type]
        agents=("Bragi",),
        limit=3,
        trace_ref="trace",
    )
    elapsed = asyncio.get_running_loop().time() - before

    assert result.timed_out is False
    assert result.results == (
        "list_agent_capabilities",
        "read_routing_policy",
        "read_action_runs",
    )
    assert starts == ["list_agent_capabilities", "read_routing_policy", "read_action_runs"]
    assert elapsed < 0.12


def test_candidate_guard_source_rate_deque_is_bounded() -> None:
    guard = CandidateGuard(max_repeats=20_000, max_source_candidates=3, clock=lambda: 1.0)
    candidate = {
        "proposal_kind": "new",
        "proposed_by": "Norns",
        "source_signal": "investigation_strategy_comparison_cohort",
        "target_rule_id": "rule-1",
        "evidence": {"occurrence_count": 1, "candidate_digest": "same"},
    }

    for _ in range(10_000):
        guard.inspect(candidate)

    events = guard._source_events.get("Norns|rule-1|investigation_strategy_comparison_cohort")
    assert events is not None
    assert len(events) == 4


def test_introspection_mentioned_uses_mapping_lookup_for_large_indexes() -> None:
    class IndexedCandidates(dict[str, object]):
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("mentioned() must not scan mapping candidates")

    candidates = IndexedCandidates({f"scope-{index}": object() for index in range(10_000)})

    assert mentioned("show scope-9999 now", candidates) == ["scope-9999"]


async def test_context_index_worker_validation_does_not_reserialize_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = ContextIndexMessage.create(
        phase="prepare",
        correlation_id="context-index-bound",
        body={"payload": "x" * 1024},
    )
    result = ContextIndexMessage.create(
        phase="prepared",
        correlation_id=message.correlation_id,
        body=message.body,
    )
    agent = Muninn()
    published: list[dict[str, object]] = []

    class Bus:
        async def publish(self, principal: str, topic: str, payload: dict[str, object]) -> None:
            del principal, topic
            published.append(payload)

    async def worker(_message: ContextIndexMessage) -> ContextIndexMessage:
        return result

    def fail_model_dump_json(self: ContextIndexMessage) -> str:
        del self
        raise AssertionError("worker results must not be JSON round-tripped")

    monkeypatch.setattr(ContextIndexMessage, "model_dump_json", fail_model_dump_json)
    agent.bind_bus(Bus())  # type: ignore[arg-type]

    await owned_context_index_handler(
        agent,
        bindings=ContextIndexWorkerBindings(muninn=worker, heimdall=worker, saga=worker),
        fallback=lambda _topic, _payload: asyncio.sleep(0),
    )(message.topic, message.model_dump(mode="json"))

    assert published == [result.model_dump(mode="json")]
