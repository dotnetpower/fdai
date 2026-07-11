"""Wave 6+ integration tests: pantheon agents against provider Protocols.

These wire the pantheon to the real
:class:`~fdai.shared.providers.event_bus.EventBus` and
:class:`~fdai.shared.providers.state_store.StateStore` Protocols using
the in-memory test doubles that ship in
:mod:`fdai.shared.providers.testing`. Behavior verified in W2 - W8 is
re-exercised through the Protocol boundary so pantheon code stays
usable against a real Postgres + Kafka backend without change.
"""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.provider_adapters import (
    StateStoreAuditChainAdapter,
    StateStoreKvAdapter,
)
from fdai.agents._framework.registry import PantheonRegistryError, load_pantheon
from fdai.agents.forseti import Forseti
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

# ---------------------------------------------------------------------------
# EventBusBridge
# ---------------------------------------------------------------------------


def test_bridge_enforces_single_writer_on_publish() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    # Owner Forseti can publish to object.verdict.
    receipt = asyncio.run(
        bridge.publish(
            "Forseti",
            "object.verdict",
            {"correlation_id": "c", "risk_verdict": "auto"},
        )
    )
    assert receipt.topic == "object.verdict"
    assert receipt.offset == 0


def test_bridge_rejects_wrong_owner_publish() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    with pytest.raises(PantheonRegistryError, match="not the owner"):
        asyncio.run(bridge.publish("Bragi", "object.verdict", {"correlation_id": "c"}))


def test_bridge_injects_producer_principal_in_payload() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    asyncio.run(
        bridge.publish("Thor", "object.action-run", {"correlation_id": "c", "resource_id": "r"})
    )

    # Peek via a fresh consumer group
    async def _first_record() -> dict:
        async for env in provider.subscribe("object.action-run", "test"):
            return dict(env.payload)
        return {}

    payload = asyncio.run(_first_record())
    assert payload["producer_principal"] == "Thor"


def test_bridge_partitions_mutation_by_resource_id() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    asyncio.run(
        bridge.publish(
            "Thor",
            "object.action-run",
            {"correlation_id": "c", "resource_id": "vm-1"},
        )
    )

    async def _first_key() -> str:
        async for env in provider.subscribe("object.action-run", "test-p"):
            return env.key
        return ""

    key = asyncio.run(_first_key())
    assert key == "vm-1"


def test_bridge_run_dispatches_to_registered_subscriber() -> None:
    """A subscribed handler must receive published payloads via the
    provider's async iterator."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    received: list[dict] = []

    async def handler(topic: str, payload: dict) -> None:
        received.append(dict(payload))

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> None:
        # Publish first so the queue has a record.
        await bridge.publish("Huginn", "object.event", {"correlation_id": "c", "event_type": "e"})
        # Run consumers briefly, then stop.
        run_task = asyncio.create_task(bridge.run())
        # Yield control so the consumer(s) can drain.
        for _ in range(20):
            await asyncio.sleep(0)
            if received:
                break
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    assert len(received) == 1
    assert received[0]["event_type"] == "e"


def test_bridge_dead_letters_on_handler_failure() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def boom(_topic: str, _payload: dict) -> None:
        raise RuntimeError("kaboom")

    bridge.subscribe("object.event", "Heimdall", boom)

    async def _drive() -> None:
        await bridge.publish("Huginn", "object.event", {"correlation_id": "c", "event_type": "e"})
        run_task = asyncio.create_task(bridge.run())
        for _ in range(20):
            await asyncio.sleep(0)
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    # Handler failure should route the record to <topic>.dlq.

    async def _read_dlq() -> list[dict]:
        collected: list[dict] = []
        async for env in provider.subscribe("object.event.dlq", "test-dlq"):
            collected.append(dict(env.payload))
        return collected

    dlq = asyncio.run(_read_dlq())
    assert len(dlq) == 1
    # InMemoryEventBus.dead_letter wraps the original payload under `payload`.
    assert dlq[0]["original_topic"] == "object.event"
    assert dlq[0]["payload"]["event_type"] == "e"


def test_bridge_isolates_crashed_consumer_from_siblings() -> None:
    """One consumer raising MUST NOT cancel sibling consumers on the same
    topic (blast-radius isolation)."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    survived: list[dict] = []

    async def boom(_t: str, _p: dict) -> None:
        raise RuntimeError("kaboom")

    async def good(_t: str, p: dict) -> None:
        survived.append(dict(p))

    bridge.subscribe("object.event", "Heimdall", boom)
    bridge.subscribe("object.event", "Forseti", good)

    async def _drive() -> None:
        await bridge.publish("Huginn", "object.event", {"correlation_id": "c", "event_type": "e"})
        run_task = asyncio.create_task(bridge.run())
        for _ in range(30):
            await asyncio.sleep(0)
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    assert len(survived) == 1  # sibling delivered despite the sibling crash
    assert bridge.metrics.handler_errors == 1
    assert bridge.metrics.dead_lettered == 1
    assert bridge.metrics.delivered == 1


def test_bridge_isolates_dead_letter_failure() -> None:
    """A DLQ write failing MUST NOT crash the consumer - it is counted and
    swallowed so the subscription keeps running."""

    class BadDlqBus(InMemoryEventBus):
        async def dead_letter(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("dlq unavailable")

    reg = load_pantheon()
    provider = BadDlqBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def boom(_t: str, _p: dict) -> None:
        raise RuntimeError("kaboom")

    bridge.subscribe("object.event", "Heimdall", boom)

    async def _drive() -> None:
        await bridge.publish("Huginn", "object.event", {"correlation_id": "c", "event_type": "e"})
        run_task = asyncio.create_task(bridge.run())
        for _ in range(30):
            await asyncio.sleep(0)
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    assert bridge.metrics.dead_letter_errors == 1
    assert bridge.metrics.consumers_crashed == 0  # DLQ failure did not kill it


def test_bridge_counts_empty_partition_key() -> None:
    """A publish whose partition key resolves to empty is counted (loss of
    per-resource ordering) rather than silently round-robined."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    # object.verdict keys on correlation_id; absent -> empty key.
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"risk_verdict": "auto"}))
    assert bridge.metrics.empty_partition_keys == 1


def test_bridge_snapshot_exposes_metrics() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    snap = bridge.snapshot()
    assert snap["consumers_live"] == 0
    assert "metrics" in snap
    assert snap["metrics"]["delivered"] == 0


def test_bridge_counts_published() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "d"}))
    assert bridge.metrics.published == 2
    assert bridge.metrics.publish_errors == 0


def test_bridge_counts_publish_error_and_reraises() -> None:
    """A broker publish failure is counted and re-raised (fail closed)."""

    class BadPublishBus(InMemoryEventBus):
        async def publish(self, *args: object, **kwargs: object):  # type: ignore[override]
            raise RuntimeError("broker down")

    reg = load_pantheon()
    bridge = EventBusBridge(provider=BadPublishBus(), registry=reg)
    with pytest.raises(RuntimeError, match="broker down"):
        asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    assert bridge.metrics.publish_errors == 1
    assert bridge.metrics.published == 0


def test_bridge_stamps_schema_version() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    assert provider._records["object.verdict"][0][1]["schema_version"] == 1
    # A caller-supplied version is not overwritten.
    asyncio.run(
        bridge.publish("Forseti", "object.verdict", {"correlation_id": "d", "schema_version": 99})
    )
    assert provider._records["object.verdict"][1][1]["schema_version"] == 99


def test_bridge_counts_missing_correlation_id() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"risk_verdict": "auto"}))
    assert bridge.metrics.missing_correlation_id == 1


def test_bridge_counts_missing_idempotency_key_on_mutation_topic() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    # object.action-run is a mutation topic; no idempotency_key -> counted.
    asyncio.run(
        bridge.publish("Thor", "object.action-run", {"correlation_id": "c", "resource_id": "vm-1"})
    )
    assert bridge.metrics.missing_idempotency_key == 1
    # A judgment topic without idempotency_key is NOT counted (not required).
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    assert bridge.metrics.missing_idempotency_key == 1


def _drain(bridge: EventBusBridge) -> None:
    """Run the bridge consumers until the finite in-memory streams drain."""

    async def _go() -> None:
        run_task = asyncio.create_task(bridge.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_go())


def test_bridge_rejects_impostor_producer_principal_on_consume() -> None:
    """Consumer-side single-writer check: a record whose producer_principal
    is not the topic owner is dead-lettered, never delivered."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    seen: list[dict] = []

    async def handler(_t: str, p: dict) -> None:
        seen.append(p)

    bridge.subscribe("object.verdict", "Thor", handler)
    # Publish straight to the provider (bypassing bridge auth) with a
    # forged principal - simulating a compromised / buggy producer.
    asyncio.run(
        provider.publish(
            "object.verdict",
            "corr-1",
            {"correlation_id": "corr-1", "producer_principal": "Bragi"},
        )
    )
    _drain(bridge)

    assert seen == []  # impostor never reached the handler
    assert bridge.metrics.producer_principal_mismatch == 1
    assert bridge.metrics.dead_lettered == 1


def test_bridge_allows_authentic_producer_principal_on_consume() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    seen: list[dict] = []

    async def handler(_t: str, p: dict) -> None:
        seen.append(p)

    bridge.subscribe("object.verdict", "Thor", handler)
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "corr-1"}))
    _drain(bridge)

    assert len(seen) == 1
    assert bridge.metrics.producer_principal_mismatch == 0


def test_bridge_verify_producer_principal_can_be_disabled() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg, verify_producer_principal=False)

    seen: list[dict] = []

    async def handler(_t: str, p: dict) -> None:
        seen.append(p)

    bridge.subscribe("object.verdict", "Thor", handler)
    asyncio.run(
        provider.publish(
            "object.verdict",
            "corr-1",
            {"correlation_id": "corr-1", "producer_principal": "Bragi"},
        )
    )
    _drain(bridge)

    assert len(seen) == 1  # delivered despite the mismatch
    assert bridge.metrics.producer_principal_mismatch == 0


def test_bridge_retries_transient_handler_failure_before_delivery() -> None:
    """A handler that fails then succeeds is retried in place (no DLQ)."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider, registry=reg, handler_max_retries=3, handler_retry_backoff=0.0
    )

    calls = {"n": 0}

    async def flaky(_t: str, _p: dict) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")

    bridge.subscribe("object.verdict", "Thor", flaky)
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    _drain(bridge)

    assert calls["n"] == 3
    assert bridge.metrics.delivered == 1
    assert bridge.metrics.handler_retries == 2
    assert bridge.metrics.dead_lettered == 0


def test_bridge_dead_letters_after_retries_exhausted() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider, registry=reg, handler_max_retries=2, handler_retry_backoff=0.0
    )

    async def always_fail(_t: str, _p: dict) -> None:
        raise RuntimeError("permanent")

    bridge.subscribe("object.verdict", "Thor", always_fail)
    asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    _drain(bridge)

    assert bridge.metrics.handler_retries == 2
    assert bridge.metrics.handler_errors == 1
    assert bridge.metrics.dead_lettered == 1


def test_bridge_skips_duplicate_subscription() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def handler(_t: str, _p: dict) -> None:
        return None

    bridge.subscribe("object.verdict", "Thor", handler)
    bridge.subscribe("object.verdict", "Thor", handler)  # duplicate -> skipped
    assert len(bridge._subs["object.verdict"]) == 1


def test_bridge_warns_on_unknown_object_topic(caplog: pytest.LogCaptureFixture) -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def handler(_t: str, _p: dict) -> None:
        return None

    with caplog.at_level("WARNING"):
        bridge.subscribe("object.verdit", "Thor", handler)  # typo
    assert any("unknown_topic" in r.message for r in caplog.records)


def test_bridge_fail_closed_on_empty_mutation_key() -> None:
    """A mutation record with no partition key is refused (fail toward safety)."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(bridge.publish("Thor", "object.action-run", {}))
    assert bridge.metrics.empty_partition_keys == 1
    assert bridge.metrics.publish_errors == 1
    assert "object.action-run" not in provider._records


def test_bridge_empty_mutation_key_soft_mode_publishes() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider, registry=reg, fail_closed_on_empty_mutation_key=False
    )
    asyncio.run(bridge.publish("Thor", "object.action-run", {}))
    assert bridge.metrics.empty_partition_keys == 1
    assert bridge.metrics.published == 1


def test_bridge_halts_ordered_topic_on_poison() -> None:
    """With halt enabled, a poison mutation record stops the consumer so a
    later mutation on the same resource cannot jump ahead of it."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider, registry=reg, halt_ordered_topic_on_poison=True
    )

    seen: list[str] = []

    async def handler(_t: str, p: dict) -> None:
        if p.get("seq") == 1:
            raise RuntimeError("poison")
        seen.append(str(p.get("seq")))

    bridge.subscribe("object.action-run", "Vidar", handler)
    common = {"resource_id": "vm-1", "correlation_id": "c", "idempotency_key": "k"}
    asyncio.run(bridge.publish("Thor", "object.action-run", {**common, "seq": 1}))
    asyncio.run(bridge.publish("Thor", "object.action-run", {**common, "seq": 2}))
    _drain(bridge)

    assert seen == []  # seq=2 never jumped ahead of the poison seq=1
    assert bridge.metrics.ordered_poison_halts == 1
    assert bridge.metrics.dead_lettered == 1


class _FlakyBus(InMemoryEventBus):
    """Subscribe raises the first ``fail_times`` calls, then succeeds."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._fail_times = fail_times
        self._calls = 0

    def subscribe(self, topic: str, group_id: str):  # type: ignore[override]
        self._calls += 1
        if self._calls <= self._fail_times:
            return self._boom()
        return super().subscribe(topic, group_id)

    async def _boom(self):
        raise RuntimeError("subscribe failed")
        yield  # pragma: no cover - makes this an async generator


class _AlwaysFailBus(InMemoryEventBus):
    def subscribe(self, topic: str, group_id: str):  # type: ignore[override]
        return self._boom()

    async def _boom(self):
        raise RuntimeError("subscribe always fails")
        yield  # pragma: no cover - makes this an async generator


async def _spin(bridge: EventBusBridge, ticks: int = 80) -> None:
    run_task = asyncio.create_task(bridge.run())
    for _ in range(ticks):
        await asyncio.sleep(0)
    await bridge.stop()
    run_task.cancel()
    try:
        await run_task
    except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
        pass


def test_consumer_self_heals_after_transient_subscribe_failure() -> None:
    reg = load_pantheon()
    provider = _FlakyBus(fail_times=2)
    bridge = EventBusBridge(
        provider=provider,
        registry=reg,
        restart_backoff_base=0.0,
        restart_backoff_max=0.0,
    )
    got: list[dict] = []

    async def handler(_t: str, p: dict) -> None:
        got.append(dict(p))

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> None:
        await bridge.publish("Huginn", "object.event", {"correlation_id": "c", "event_type": "e"})
        await _spin(bridge)

    asyncio.run(_drive())
    assert bridge.metrics.consumers_restarted == 2
    assert len(got) == 1  # recovered on the 3rd subscribe and delivered


def test_consumer_gives_up_after_max_restarts() -> None:
    reg = load_pantheon()
    provider = _AlwaysFailBus()
    bridge = EventBusBridge(
        provider=provider,
        registry=reg,
        max_consumer_restarts=3,
        restart_backoff_base=0.0,
        restart_backoff_max=0.0,
    )

    async def handler(_t: str, _p: dict) -> None:  # pragma: no cover - never reached
        return None

    bridge.subscribe("object.event", "Heimdall", handler)
    asyncio.run(_spin(bridge))
    assert bridge.metrics.consumers_restarted == 3
    assert bridge.metrics.consumers_crashed == 4  # 3 restarts + final give-up


def test_stop_is_bounded_and_clears_tasks() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg, shutdown_timeout=0.2)

    async def handler(_t: str, _p: dict) -> None:
        return None

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        for _ in range(5):
            await asyncio.sleep(0)
        await bridge.stop()
        assert bridge._tasks == []
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# StateStoreAuditChainAdapter
# ---------------------------------------------------------------------------


def test_state_store_audit_chain_writes_hash_linked_records() -> None:
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store=store)

    async def _write_two() -> None:
        await chain.append(
            principal="Forseti",
            topic="object.verdict",
            correlation_id="c",
            payload={"risk_verdict": "auto"},
        )
        await chain.append(
            principal="Thor",
            topic="object.action-run",
            correlation_id="c",
            payload={"state": "succeeded"},
        )

    asyncio.run(_write_two())
    chain.verify()
    assert len(chain.entries) == 2
    assert chain.entries[1].prev_hash == chain.entries[0].entry_hash


def test_state_store_audit_chain_replay_by_correlation() -> None:
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store=store)

    async def _write() -> None:
        for i in range(3):
            await chain.append(
                principal="Thor",
                topic="object.action-run",
                correlation_id="keep",
                payload={"i": i},
            )
        await chain.append(
            principal="Thor",
            topic="object.action-run",
            correlation_id="other",
            payload={"i": 99},
        )

    asyncio.run(_write())
    slice_ = chain.entries_for_correlation("keep")
    assert len(slice_) == 3
    assert all(e.correlation_id == "keep" for e in slice_)


# ---------------------------------------------------------------------------
# StateStoreKvAdapter
# ---------------------------------------------------------------------------


def test_state_store_kv_get_put_round_trip() -> None:
    store = InMemoryStateStore()
    kv = StateStoreKvAdapter(store=store)

    async def _round_trip() -> object | None:
        await kv.put("resource_state", "vm-1", {"public": False})
        return await kv.get("resource_state", "vm-1")

    got = asyncio.run(_round_trip())
    assert got == {"public": False}


def test_state_store_kv_wraps_primitives_for_protocol() -> None:
    store = InMemoryStateStore()
    kv = StateStoreKvAdapter(store=store)

    async def _put_get() -> object | None:
        await kv.put("counters", "hits", 42)
        return await kv.get("counters", "hits")

    got = asyncio.run(_put_get())
    # A scalar round-trips back to the original value (symmetric wrap/unwrap),
    # not a leaked envelope dict.
    assert got == 42


# ---------------------------------------------------------------------------
# Round-trip: Forseti publishes verdict through the bridge
# ---------------------------------------------------------------------------


def test_forseti_publishes_verdict_over_provider_event_bus() -> None:
    """Pantheon agent -> bridge -> real EventBus provider round-trip."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    forseti = Forseti(bus=bridge)  # bridge is API-compatible

    asyncio.run(
        forseti.judge(
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-1",
                "correlation_id": "c-real-bus",
            }
        )
    )

    async def _first_verdict() -> dict:
        async for env in provider.subscribe("object.verdict", "collector"):
            return dict(env.payload)
        return {}

    verdict = asyncio.run(_first_verdict())
    assert verdict["risk_verdict"] == "auto"
    assert verdict["producer_principal"] == "Forseti"


def test_in_memory_bus_isolates_payload_per_subscriber() -> None:
    # H9: each subscriber gets its own copy, so a handler that mutates the
    # payload cannot contaminate a later subscriber (or the caller).
    from fdai.agents._framework.bus import InMemoryBus

    bus = InMemoryBus(registry=load_pantheon())
    observed: dict[str, object] = {}

    async def _mutator(_topic: str, payload: dict[str, object]) -> None:
        payload["injected"] = "x"  # a buggy subscriber mutates in place

    async def _observer(_topic: str, payload: dict[str, object]) -> None:
        observed.update(payload)

    bus.subscribe("object.arbitration-request", "Odin", _mutator)
    bus.subscribe("object.arbitration-request", "Saga", _observer)

    async def _run() -> None:
        await bus.publish("Forseti", "object.arbitration-request", {"resource_id": "vm-1"})

    asyncio.run(_run())
    assert "injected" not in observed  # second subscriber saw a clean copy


def test_bridge_metrics_expose_consumers_gave_up() -> None:
    # H10: a permanently-dead subscription is observable via a dedicated
    # counter, not silently folded into consumers_crashed.
    from fdai.agents._framework.bus_bridge import BridgeMetrics

    snap = BridgeMetrics().as_dict()
    assert snap["consumers_gave_up"] == 0
