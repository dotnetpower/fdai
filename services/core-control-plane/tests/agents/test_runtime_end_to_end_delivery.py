"""Round 10 package F regressions for runtime delivery correctness."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fdai.agents._framework import runtime_subscriptions
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.ontology_index import (
    ContextIndexMessage,
    ContextIndexWorkerBindings,
    owned_context_index_handler,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.saga import InMemoryAuditChain, Saga
from fdai.shared.providers.local.event_bus import LocalEventBus

_RAW_TOPIC = "fdai.events.r10-f"


async def _wait_for(predicate: Callable[[], bool], *, steps: int = 1000) -> None:
    for _ in range(steps):
        await asyncio.sleep(0)
        if predicate():
            return
    raise AssertionError("condition was not observed")


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        return


def _payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]


def _event_payload(correlation: str = "corr-event") -> dict[str, Any]:
    return {
        "correlation_id": correlation,
        "idempotency_key": f"{correlation}:event",
        "resource_id": "resource-event",
        "event_type": "unit.test",
    }


def _action_run_payload(correlation: str = "corr-action") -> dict[str, Any]:
    return {
        "correlation_id": correlation,
        "idempotency_key": f"{correlation}:action",
        "resource_id": "resource-action",
        "state": "failed",
        "action_type": "ops.test",
    }


class _DurableAuditChain(InMemoryAuditChain):
    def __init__(self) -> None:
        super().__init__()
        self.durable = True


def test_same_agent_topic_handlers_fan_out_over_local_bus() -> None:
    provider = LocalEventBus()
    bridge = EventBusBridge(provider=provider, registry=load_pantheon(), handler_timeout=1.0)
    seen: list[str] = []

    async def first(_topic: str, payload: dict[str, Any]) -> None:
        seen.append("first:" + str(payload["correlation_id"]))

    async def second(_topic: str, payload: dict[str, Any]) -> None:
        seen.append("second:" + str(payload["correlation_id"]))

    bridge.subscribe("object.event", "Heimdall", first)
    bridge.subscribe("object.event", "Heimdall", second)

    async def drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        await bridge.publish("Huginn", "object.event", _event_payload("corr-fanout"))
        await _wait_for(lambda: len(seen) == 2)
        await bridge.stop()
        await _cancel(run_task)

    asyncio.run(drive())

    assert sorted(seen) == ["first:corr-fanout", "second:corr-fanout"]


def test_handler_failure_dlq_identifies_subscriber_and_degrades_agent() -> None:
    provider = LocalEventBus()
    bridge = EventBusBridge(provider=provider, registry=load_pantheon(), handler_timeout=1.0)

    async def failing(_topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    bridge.subscribe("object.event", "Heimdall", failing)

    async def drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        await bridge.publish("Huginn", "object.event", _event_payload("corr-dlq"))
        await _wait_for(lambda: bool(_payloads(provider, "object.event.dlq")))
        await bridge.stop()
        await _cancel(run_task)

    asyncio.run(drive())

    dlq = _payloads(provider, "object.event.dlq")[0]
    assert dlq["consumer_group"] == "fdai-pantheon.Heimdall"
    assert dlq["agent"] == "Heimdall"
    assert dlq["topic"] == "object.event"
    assert dlq["offset"] == 0
    assert dlq["payload"]["correlation_id"] == "corr-dlq"
    assert "Heimdall" in bridge.snapshot()["unavailable_agents"]


def test_invalid_owned_record_dead_letters_once_per_broker_record() -> None:
    provider = LocalEventBus()
    bridge = EventBusBridge(provider=provider, registry=load_pantheon(), handler_timeout=1.0)

    async def handler(_topic: str, _payload: dict[str, Any]) -> None:
        return None

    bridge.subscribe("object.action-run", "Saga", handler)
    bridge.subscribe("object.action-run", "Var", handler)

    async def drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        bad = _action_run_payload("corr-invalid")
        bad["producer_principal"] = "Forseti"
        bad["schema_version"] = 1
        bad["envelope_schema_version"] = 1
        await provider.publish("object.action-run", "resource-action", bad)
        await _wait_for(lambda: bool(_payloads(provider, "object.action-run.dlq")))
        await bridge.stop()
        await _cancel(run_task)

    asyncio.run(drive())

    assert len(_payloads(provider, "object.action-run.dlq")) == 1
    rejection = bridge.snapshot()["recent_rejected_edges"][0]
    assert rejection["correlation_id"] == "corr-invalid"


def test_ordered_mutation_poison_halts_topic_for_sibling_consumers() -> None:
    provider = LocalEventBus()
    bridge = EventBusBridge(provider=provider, registry=load_pantheon(), handler_timeout=1.0)
    saga_seen: list[str] = []

    async def failing(_topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("poison")

    async def saga(_topic: str, payload: dict[str, Any]) -> None:
        saga_seen.append(str(payload["correlation_id"]))

    bridge.subscribe("object.action-run", "Var", failing)
    bridge.subscribe("object.action-run", "Saga", saga)

    async def drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        await bridge.publish("Thor", "object.action-run", _action_run_payload("corr-poison-1"))
        await _wait_for(lambda: bridge.snapshot()["degraded_consumer_states"])
        await bridge.publish("Thor", "object.action-run", _action_run_payload("corr-poison-2"))
        await asyncio.sleep(0)
        await bridge.stop()
        await _cancel(run_task)

    asyncio.run(drive())

    assert "corr-poison-2" not in saga_seen
    assert bridge.snapshot()["metrics"]["ordered_poison_halts"] == 1


def test_local_event_bus_preserves_committed_offsets_until_explicit_reset() -> None:
    provider = LocalEventBus()

    async def drive() -> tuple[str, bool, str]:
        await provider.publish("topic", "key", {"value": "first"})
        stream = provider.subscribe("topic", "group")
        first = await anext(stream)
        commit_next = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        commit_next.cancel()
        with pytest.raises(asyncio.CancelledError):
            await commit_next
        await stream.aclose()
        replay = provider.subscribe("topic", "group")
        try:
            await asyncio.wait_for(anext(replay), timeout=0.01)
            replayed = True
        except TimeoutError:
            replayed = False
        await replay.aclose()
        provider.reset_offsets("topic", "group")
        reset_stream = provider.subscribe("topic", "group")
        reset = await anext(reset_stream)
        await reset_stream.aclose()
        return str(first.payload["value"]), replayed, str(reset.payload["value"])

    first, replayed, reset = asyncio.run(drive())

    assert first == "first"
    assert replayed is False
    assert reset == "first"


def test_runtime_binds_recovery_effect_observer_and_clean_stop_is_not_degraded() -> None:
    provider = LocalEventBus()

    async def observer(_topic: str, _payload: dict[str, Any]) -> None:
        return None

    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        recovery_effect_observer=observer,
    )

    subscribers = runtime.bridge._subs["object.recovery-effect-observation"]
    assert (
        runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL,
        observer,
    ) in subscribers

    async def drive() -> dict[str, Any]:
        run_task = asyncio.create_task(runtime.run())
        await _wait_for(lambda: bool(runtime.bridge._tasks))
        await runtime.stop()
        await _cancel(run_task)
        return runtime.bridge.snapshot()

    snapshot = asyncio.run(drive())

    assert snapshot["status"] == "stopped"
    assert snapshot["degraded_consumer_states"] == {}


def test_valid_hil_verdict_reaches_thor_saga_and_var_ticket() -> None:
    runtime = PantheonRuntime.build(provider=LocalEventBus(), raw_event_topic=_RAW_TOPIC)
    provider = runtime.bridge.provider
    assert isinstance(provider, LocalEventBus)

    async def drive() -> None:
        run_task = asyncio.create_task(runtime.run())
        await runtime.bridge.publish(
            "Forseti",
            "object.verdict",
            {
                "correlation_id": "corr-hil-chain",
                "idempotency_key": "verdict:corr-hil-chain",
                "resource_id": "resource-hil",
                "action_type": "ops.restart-service",
                "risk_verdict": "hil",
                "quorum_required": 1,
                "initiator_principal": "operator@example.com",
            },
        )
        await _wait_for(
            lambda: (
                bool(_payloads(provider, "object.action-run"))
                and bool(runtime.agents["Var"].pending_tickets())
                and bool(runtime.agents["Saga"].replay_for_correlation("corr-hil-chain"))
            )
        )
        await runtime.stop()
        await _cancel(run_task)

    asyncio.run(drive())

    action_run = _payloads(provider, "object.action-run")[-1]
    assert action_run["state"] == "hil_pending"
    assert action_run["correlation_id"] == "corr-hil-chain"
    assert runtime.agents["Var"].pending_tickets()[0].correlation_id == "corr-hil-chain"


def test_context_index_requires_durable_saga_and_recovers_pending_publications() -> None:
    provider = LocalEventBus()
    pending = ContextIndexMessage.create(
        phase="transition_prepared",
        correlation_id="corr-context",
        body={"source": "test"},
    )
    acknowledged: list[str] = []

    async def passthrough(message: ContextIndexMessage) -> ContextIndexMessage:
        return message

    async def published(message: ContextIndexMessage) -> None:
        acknowledged.append(message.content_key)

    async def pending_for(owner: str) -> tuple[ContextIndexMessage, ...]:
        return (pending,) if owner == "Muninn" else ()

    bindings = ContextIndexWorkerBindings(
        muninn=passthrough,
        heimdall=passthrough,
        saga=passthrough,
        published=published,
        pending=pending_for,
    )

    with pytest.raises(RuntimeError, match="durable Saga audit"):
        PantheonRuntime.build(
            provider=provider,
            raw_event_topic=_RAW_TOPIC,
            context_index_workers=bindings,
        )

    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        context_index_workers=bindings,
        saga=Saga(audit_chain=_DurableAuditChain()),
    )

    asyncio.run(runtime._rehydrate())

    records = _payloads(provider, "object.context-index")
    assert records[-1]["correlation_id"] == "corr-context"
    assert acknowledged == [pending.content_key]


def test_context_index_ack_failure_after_publish_does_not_duplicate_message() -> None:
    provider = LocalEventBus()
    saga = Saga(audit_chain=_DurableAuditChain())
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        context_index_workers=ContextIndexWorkerBindings(
            muninn=lambda message: _async_return(message),
            heimdall=lambda message: _async_return(message),
            saga=lambda message: _async_return(message),
        ),
        saga=saga,
    )
    muninn = runtime.agents["Muninn"]
    muninn.bind_bus(runtime.bridge)
    calls = 0

    async def worker(message: ContextIndexMessage) -> ContextIndexMessage:
        return ContextIndexMessage.create(
            phase="intent",
            correlation_id=message.correlation_id,
            body={"source": "next"},
        )

    async def published(_message: ContextIndexMessage) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("ack lost")

    handler = owned_context_index_handler(
        muninn,
        ContextIndexWorkerBindings(
            muninn=worker,
            heimdall=lambda message: _async_return(message),
            saga=lambda message: _async_return(message),
            published=published,
        ),
        muninn.on_typed_message,
    )
    source = ContextIndexMessage.create(
        phase="transition_validated",
        correlation_id="corr-ack",
        body={"source": "validated"},
    )

    asyncio.run(handler(source.topic, source.model_dump(mode="json")))

    assert len(_payloads(provider, "object.context-index")) == 1
    assert calls == 1


async def _async_return(value: ContextIndexMessage) -> ContextIndexMessage:
    return value


def test_measured_seconds_kpis_do_not_make_runtime_health_throw() -> None:
    runtime = PantheonRuntime.build(provider=LocalEventBus(), raw_event_topic=_RAW_TOPIC)
    huginn = runtime.agents["Huginn"]
    huginn._event_latency_seconds.append(0.01)
    huginn._event_latency_seconds.append(0.02)

    health = runtime.health()

    assert (
        health["agent_health"]["Huginn"]["kpis"]["event_processing_latency_p99_seconds"][
            "sample_count"
        ]
        == 2
    )
    assert health["kpi_coverage"]["Huginn"]["current"] > 0


def test_degradation_facts_do_not_claim_unobserved_mechanisms() -> None:
    runtime = PantheonRuntime.build(
        provider=LocalEventBus(),
        raw_event_topic=_RAW_TOPIC,
        disabled_agents=frozenset({"Forseti", "Odin", "Var"}),
    )

    facts = runtime.health()["degradation"]["facts"]

    assert facts["Var"]["queue_preserved"]["evidence_state"] == "not_observed"
    assert facts["Var"]["timeouts_auto_extended"]["evidence_state"] == "not_observed"
    assert facts["Forseti"]["operator_alert"]["evidence_state"] == "not_observed"
    assert facts["Odin"]["terminal_hil_closure"]["evidence_state"] == "not_observed"
