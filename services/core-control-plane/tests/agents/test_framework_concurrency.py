"""Concurrency, timeout, and cancellation regressions for pantheon framework seams."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.agents._framework.base import Agent, run_cancellation_safe_critical_section
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import (
    AgentHandlerObserver,
    AgentHandlerPhase,
    EventBusBridge,
)
from fdai.agents._framework.execution_safety import _run_agent_maintenance
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents._framework.registry import load_pantheon
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _spec(name: str):
    return next(spec for spec in PANTHEON_SPECS if spec.name == name)


def _payload(kind: str = "event") -> dict[str, object]:
    return {
        "correlation_id": f"corr-{kind}",
        "idempotency_key": f"{kind}:corr-{kind}",
    }


async def test_inmemory_timeout_waits_for_handler_critical_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = InMemoryBus(registry=load_pantheon(), handler_timeout=0.01)
    entered = asyncio.Event()
    cancellation_requested = asyncio.Event()
    release = asyncio.Event()
    committed: list[str] = []

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        async def critical() -> None:
            entered.set()
            await release.wait()
            committed.append("done")

        try:
            await run_cancellation_safe_critical_section(critical())
        except asyncio.CancelledError:
            cancellation_requested.set()
            raise

    async def deterministic_wait_for(awaitable, _timeout):  # type: ignore[no-untyped-def]
        task = asyncio.ensure_future(awaitable)
        await entered.wait()
        task.cancel()
        cancellation_requested.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        raise TimeoutError

    monkeypatch.setattr("fdai.agents._framework.bus.asyncio.wait_for", deterministic_wait_for)
    bus.subscribe("object.event", "Heimdall", handler)
    publish_task = asyncio.create_task(bus.publish("Huginn", "object.event", _payload()))
    await entered.wait()
    await cancellation_requested.wait()
    assert not publish_task.done()

    release.set()
    await publish_task

    assert committed == ["done"]
    assert bus.handler_errors == 1
    assert len(bus.dead_letters) == 1


async def test_bridge_timeout_waits_for_handler_critical_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = EventBusBridge(
        provider=InMemoryEventBus(),
        registry=load_pantheon(),
        handler_timeout=0.01,
    )
    entered = asyncio.Event()
    cancellation_requested = asyncio.Event()
    release = asyncio.Event()
    committed: list[str] = []

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        async def critical() -> None:
            entered.set()
            await release.wait()
            committed.append("done")

        try:
            await run_cancellation_safe_critical_section(critical())
        except asyncio.CancelledError:
            cancellation_requested.set()
            raise

    async def deterministic_wait_for(awaitable, _timeout):  # type: ignore[no-untyped-def]
        task = asyncio.ensure_future(awaitable)
        await entered.wait()
        task.cancel()
        cancellation_requested.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        raise TimeoutError

    monkeypatch.setattr(
        "fdai.agents._framework.bus_bridge.asyncio.wait_for",
        deterministic_wait_for,
    )
    deliver_task = asyncio.create_task(bridge._deliver("object.event", handler, _payload()))
    await entered.wait()
    await cancellation_requested.wait()
    assert not deliver_task.done()

    release.set()
    with pytest.raises(TimeoutError):
        await deliver_task

    assert committed == ["done"]


class _BlockingPublishBus:
    def __init__(self) -> None:
        self.published = asyncio.Event()
        self.cancel_observed = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        assert principal == "Mimir"
        assert topic == "object.rule"
        assert payload["correlation_id"]
        assert payload["idempotency_key"]
        self.calls += 1
        self.published.set()
        await self.release.wait()


async def test_flush_cancel_after_publish_does_not_republish_or_leak_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(_spec("Mimir"))
    bus = _BlockingPublishBus()
    agent.bind_bus(bus)
    agent._proposal_limiter = RateLimiter(per_minute=1, per_hour=1, now=lambda: 10.0)
    agent._proposal_queue.append(("object.rule", _payload("rule")))

    async def observed_critical(operation):  # type: ignore[no-untyped-def]
        task = asyncio.ensure_future(operation)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            bus.cancel_observed.set()
            await task
            raise

    monkeypatch.setattr(
        "fdai.agents._framework.base.run_cancellation_safe_critical_section",
        observed_critical,
    )
    flush_task = asyncio.create_task(agent.flush_rate_limited_proposals())
    await bus.published.wait()
    flush_task.cancel()
    await asyncio.wait_for(bus.cancel_observed.wait(), 1.0)
    assert not flush_task.done()

    bus.release.set()
    with pytest.raises(asyncio.CancelledError):
        await flush_task

    assert list(agent._proposal_queue) == []
    assert bus.calls == 1
    assert await agent.flush_rate_limited_proposals() == 0
    assert bus.calls == 1


class _RacingStateStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self._first_reads = 0
        self._release_reads = asyncio.Event()

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        if key.endswith("/shared") and self._first_reads < 2:
            self._first_reads += 1
            if self._first_reads == 2:
                self._release_reads.set()
            await self._release_reads.wait()
            return None
        return await super().read_state(key)


async def test_durable_rate_limiter_reservation_uses_atomic_cas() -> None:
    store = _RacingStateStore()
    first = RateLimiter(
        per_minute=1, per_hour=1, now=lambda: 20.0, state_store=store, scope="shared"
    )
    second = RateLimiter(
        per_minute=1,
        per_hour=1,
        now=lambda: 20.0,
        state_store=store,
        scope="shared",
    )

    reservations = await asyncio.gather(first.reserve(), second.reserve())

    assert sum(reservation is not None for reservation in reservations) == 1
    for reservation in reservations:
        if reservation is not None:
            await reservation.commit()

    assert await first.reserve() is None


class _HangingObserver(AgentHandlerObserver):
    async def observe(
        self,
        *,
        agent: str,
        topic: str,
        phase: AgentHandlerPhase,
        payload: Mapping[str, object],
        error_type: str | None = None,
    ) -> None:
        del agent, topic, phase, payload, error_type
        await asyncio.Event().wait()


async def test_handler_observer_timeout_does_not_block_delivery() -> None:
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        handler_observer=_HangingObserver(),
        handler_observer_timeout=0.01,
    )
    delivered = asyncio.Event()

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        delivered.set()

    bridge.subscribe("object.verdict", "Thor", handler)
    await provider.publish(
        "object.verdict",
        "corr-verdict",
        {
            **_payload("verdict"),
            "producer_principal": "Forseti",
        },
    )
    await bridge.run()

    assert delivered.is_set()
    assert bridge.metrics.delivered == 1


class _HangingDeadLetterBus(InMemoryEventBus):
    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        del topic, key, payload, reason
        await asyncio.Event().wait()


async def test_ordered_consumer_halts_when_dead_letter_times_out() -> None:
    provider = _HangingDeadLetterBus()
    halt_store = InMemoryStateStore()
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        dead_letter_timeout=0.01,
        dead_letter_max_retries=0,
        halt_state_store=halt_store,
    )

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        raise RuntimeError("poison")

    bridge.subscribe("object.action-run", "Heimdall", handler)
    await provider.publish(
        "object.action-run",
        "vm-1",
        {
            **_payload("action-run"),
            "producer_principal": "Thor",
            "resource_id": "vm-1",
        },
    )
    await bridge.run()

    snapshot = bridge.snapshot()
    assert snapshot["consumer_states"] == {"Heimdall:object.action-run": "halted"}
    assert bridge.metrics.dead_letter_errors == 1
    assert bridge.metrics.ordered_poison_halts == 1


async def test_maintenance_timeout_does_not_cancel_tick() -> None:
    agent = Agent(_spec("Mimir"))
    started = asyncio.Event()
    release = asyncio.Event()
    committed = asyncio.Event()

    async def maintenance_tick() -> None:
        started.set()
        await release.wait()
        committed.set()

    agent.maintenance_tick = maintenance_tick  # type: ignore[method-assign]

    await _run_agent_maintenance(agent, 0.01)
    assert agent.behavior_snapshot()["maintenance_tick:timeout"] == 1
    assert started.is_set()
    assert not committed.is_set()

    release.set()
    await asyncio.wait_for(committed.wait(), 1.0)
