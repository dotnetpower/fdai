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
import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, replace

import pytest
from fdai.agents._framework import audit_chain_journal, audit_chain_rehydrate
from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.agents._framework.audit_chain_journal import AUDIT_CHECKPOINT_KEY, entry_hash
from fdai.agents._framework.bus_bridge import AgentHandlerPhase, EventBusBridge
from fdai.agents._framework.provider_adapters import (
    StateStoreAuditChainAdapter,
    StateStoreKvAdapter,
)
from fdai.agents._framework.registry import PantheonRegistryError, load_pantheon
from fdai.agents.forseti import Forseti
from fdai.shared.providers.state_store import AUDIT_CHAIN_ENTRY_FIELDS, is_audit_chain_record
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

# ---------------------------------------------------------------------------
# EventBusBridge
# ---------------------------------------------------------------------------


def _verdict_payload(correlation_id: str = "c", **extra: object) -> dict[str, object]:
    return {
        "correlation_id": correlation_id,
        "idempotency_key": f"verdict:{correlation_id}",
        **extra,
    }


def _event_payload(correlation_id: str = "c", **extra: object) -> dict[str, object]:
    return {
        "correlation_id": correlation_id,
        "idempotency_key": f"event:{correlation_id}",
        **extra,
    }


def test_bridge_enforces_single_writer_on_publish() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    # Owner Forseti can publish to object.verdict.
    receipt = asyncio.run(
        bridge.publish(
            "Forseti",
            "object.verdict",
            _verdict_payload(risk_verdict="auto"),
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
        bridge.publish(
            "Thor",
            "object.action-run",
            {"correlation_id": "c", "resource_id": "r", "idempotency_key": "idem-c"},
        )
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
            {
                "correlation_id": "c",
                "resource_id": "vm-1",
                "idempotency_key": "idem-c",
            },
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
        await bridge.publish("Huginn", "object.event", _event_payload(event_type="e"))
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


def test_bridge_observes_actual_handler_lifecycle() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    observed: list[tuple[str, str, AgentHandlerPhase, str]] = []

    class Observer:
        async def observe(
            self,
            *,
            agent: str,
            topic: str,
            phase: AgentHandlerPhase,
            payload: Mapping[str, object],
            error_type: str | None = None,
        ) -> None:
            observed.append((agent, topic, phase, str(payload.get("correlation_id"))))

    bridge = EventBusBridge(provider=provider, registry=reg, handler_observer=Observer())

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        return None

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> None:
        await bridge.publish(
            "Huginn",
            "object.event",
            _event_payload("corr-observed", event_type="resource.changed"),
        )
        await bridge.run()

    asyncio.run(_drive())

    assert observed == [
        ("Heimdall", "object.event", AgentHandlerPhase.STARTED, "corr-observed"),
        ("Heimdall", "object.event", AgentHandlerPhase.COMPLETED, "corr-observed"),
    ]


def test_bridge_observer_failure_does_not_block_handler_delivery() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    delivered: list[str] = []

    class FailingObserver:
        async def observe(
            self,
            *,
            agent: str,
            topic: str,
            phase: AgentHandlerPhase,
            payload: Mapping[str, object],
            error_type: str | None = None,
        ) -> None:
            raise RuntimeError("observer unavailable")

    bridge = EventBusBridge(
        provider=provider,
        registry=reg,
        handler_observer=FailingObserver(),
    )

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        delivered.append(str(payload["correlation_id"]))

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> None:
        await bridge.publish(
            "Huginn",
            "object.event",
            _event_payload("corr-delivered", event_type="resource.changed"),
        )
        await bridge.run()

    asyncio.run(_drive())

    assert delivered == ["corr-delivered"]


def test_bridge_summarizes_handler_observer_recovery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reg = load_pantheon()

    class FlakyObserver:
        attempts = 0

        async def observe(
            self,
            *,
            agent: str,
            topic: str,
            phase: AgentHandlerPhase,
            payload: Mapping[str, object],
            error_type: str | None = None,
        ) -> None:
            self.attempts += 1
            if self.attempts < 3:
                raise RuntimeError("observer unavailable")

    bridge = EventBusBridge(
        provider=InMemoryEventBus(),
        registry=reg,
        handler_observer=FlakyObserver(),
    )

    async def _drive() -> None:
        for _ in range(3):
            await bridge._notify_handler_observer(
                agent="Heimdall",
                topic="object.event",
                phase=AgentHandlerPhase.STARTED,
                payload={"correlation_id": "corr-recovery"},
            )

    with caplog.at_level(logging.INFO, logger="fdai.agents._framework.bus_bridge"):
        asyncio.run(_drive())

    recovery = next(
        record
        for record in caplog.records
        if record.message == "pantheon_handler_observer_recovered"
    )
    assert recovery.agent == "Heimdall"
    assert recovery.topic == "object.event"
    assert recovery.phase == "started"
    assert recovery.failure_count == 2


def test_bridge_skips_observer_for_non_pantheon_principal() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    observed: list[str] = []
    delivered: list[str] = []

    class Observer:
        async def observe(
            self,
            *,
            agent: str,
            topic: str,
            phase: AgentHandlerPhase,
            payload: Mapping[str, object],
            error_type: str | None = None,
        ) -> None:
            observed.append(agent)

    bridge = EventBusBridge(provider=provider, registry=reg, handler_observer=Observer())

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        delivered.append(str(payload["correlation_id"]))

    bridge.subscribe("object.event", "runtime-observer", handler)

    async def _drive() -> None:
        await bridge.publish(
            "Huginn",
            "object.event",
            _event_payload("corr-internal", event_type="resource.changed"),
        )
        await bridge.run()

    asyncio.run(_drive())

    assert delivered == ["corr-internal"]
    assert observed == []


def test_bridge_dead_letters_on_handler_failure() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def boom(_topic: str, _payload: dict) -> None:
        raise RuntimeError("kaboom")

    bridge.subscribe("object.event", "Heimdall", boom)

    async def _drive() -> None:
        await bridge.publish("Huginn", "object.event", _event_payload(event_type="e"))
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
        await bridge.publish("Huginn", "object.event", _event_payload(event_type="e"))
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


def test_bridge_fanout_subscribers_run_concurrently() -> None:
    """A slow subscriber MUST NOT serialize an independent sibling."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    slow_finished = asyncio.Event()
    fast_finished = asyncio.Event()

    async def slow(_topic: str, _payload: dict) -> None:
        slow_started.set()
        await release_slow.wait()
        slow_finished.set()

    async def fast(_topic: str, _payload: dict) -> None:
        fast_finished.set()

    bridge.subscribe("object.event", "Heimdall", slow)
    bridge.subscribe("object.event", "Forseti", fast)

    async def _drive() -> None:
        await bridge.publish(
            "Huginn",
            "object.event",
            _event_payload("corr-fanout", event_type="resource.changed"),
        )
        run_task = asyncio.create_task(bridge.run())
        try:
            await asyncio.wait_for(fast_finished.wait(), timeout=1.0)
            assert slow_started.is_set()
            assert not slow_finished.is_set()
        finally:
            release_slow.set()
            await run_task

    asyncio.run(_drive())
    assert bridge.metrics.delivered == 2


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
        await bridge.publish("Huginn", "object.event", _event_payload(event_type="e"))
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


def test_bridge_rejects_incomplete_owned_envelope() -> None:
    """A missing owned-topic envelope fails closed and is counted."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    with pytest.raises(ValueError, match="correlation_id, idempotency_key"):
        asyncio.run(bridge.publish("Forseti", "object.verdict", {"risk_verdict": "auto"}))
    assert bridge.metrics.invalid_envelope_fields == 2
    assert bridge.metrics.publish_errors == 1


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
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload("d")))
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
        asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
    assert bridge.metrics.publish_errors == 1
    assert bridge.metrics.published == 0


def test_bridge_stamps_schema_version() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
    assert provider._records["object.verdict"][0][1]["schema_version"] == 1
    assert provider._records["object.verdict"][0][1]["envelope_schema_version"] == 1
    # A domain contract keeps its own schema version while the transport
    # version remains authoritative in a separate field.
    asyncio.run(
        bridge.publish("Forseti", "object.verdict", _verdict_payload("d", schema_version=99))
    )
    assert provider._records["object.verdict"][1][1]["schema_version"] == 99
    assert provider._records["object.verdict"][1][1]["envelope_schema_version"] == 1


def test_bridge_counts_missing_correlation_id() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    with pytest.raises(ValueError, match="correlation_id"):
        asyncio.run(bridge.publish("Forseti", "object.verdict", {"risk_verdict": "auto"}))
    assert bridge.metrics.missing_correlation_id == 1


def test_bridge_rejects_missing_idempotency_key_on_mutation_topic() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    with pytest.raises(ValueError, match="idempotency_key"):
        asyncio.run(
            bridge.publish(
                "Thor",
                "object.action-run",
                {"correlation_id": "c", "resource_id": "vm-1"},
            )
        )
    assert bridge.metrics.missing_idempotency_key == 1
    assert "object.action-run" not in provider._records
    with pytest.raises(ValueError, match="idempotency_key"):
        asyncio.run(bridge.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    assert bridge.metrics.missing_idempotency_key == 2


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
            _verdict_payload("corr-1", producer_principal="Bragi"),
        )
    )
    _drain(bridge)

    assert seen == []  # impostor never reached the handler
    assert bridge.metrics.producer_principal_mismatch == 1
    assert bridge.metrics.dead_lettered == 1


def test_bridge_rejects_missing_producer_principal_on_owned_topic() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    seen: list[dict] = []

    async def handler(_topic: str, payload: dict) -> None:
        seen.append(payload)

    bridge.subscribe("object.verdict", "Thor", handler)
    asyncio.run(provider.publish("object.verdict", "corr-1", _verdict_payload("corr-1")))
    _drain(bridge)
    assert seen == []
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
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload("corr-1")))
    _drain(bridge)

    assert len(seen) == 1
    assert bridge.metrics.producer_principal_mismatch == 0


def test_bridge_owned_topic_principal_verification_cannot_be_disabled() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    seen: list[dict] = []

    async def handler(_t: str, p: dict) -> None:
        seen.append(p)

    bridge.subscribe("object.verdict", "Thor", handler)
    asyncio.run(
        provider.publish(
            "object.verdict",
            "corr-1",
            _verdict_payload("corr-1", producer_principal="Bragi"),
        )
    )
    _drain(bridge)

    assert seen == []
    assert bridge.metrics.producer_principal_mismatch == 1


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
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
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
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
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


def test_bridge_rejects_unknown_object_topic() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def handler(_t: str, _p: dict) -> None:
        return None

    with pytest.raises(ValueError, match="unknown pantheon object topic"):
        bridge.subscribe("object.verdit", "Thor", handler)  # typo


def test_bridge_fail_closed_on_empty_mutation_key() -> None:
    """A mutation record with no partition key is refused (fail toward safety)."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)
    with pytest.raises(ValueError, match="correlation_id, idempotency_key"):
        asyncio.run(bridge.publish("Thor", "object.action-run", {}))
    assert bridge.metrics.missing_correlation_id == 1
    assert bridge.metrics.missing_resource_id == 1
    assert bridge.metrics.missing_idempotency_key == 1
    assert bridge.metrics.publish_errors == 1
    assert "object.action-run" not in provider._records


def test_bridge_empty_mutation_key_soft_mode_cannot_bypass_envelope() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    with pytest.raises(TypeError, match="fail_closed_on_empty_mutation_key"):
        EventBusBridge(
            provider=provider,
            registry=reg,
            fail_closed_on_empty_mutation_key=False,  # type: ignore[call-arg]
        )


def test_bridge_halts_ordered_topic_on_poison() -> None:
    """With halt enabled, a poison mutation record stops the consumer so a
    later mutation on the same resource cannot jump ahead of it."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg, halt_ordered_topic_on_poison=True)

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


def test_bridge_payload_validator_rejects_malformed() -> None:
    """A publish-side contract check rejects a malformed record (fail closed)."""

    def validator(topic: str, payload) -> None:
        if topic == "object.verdict" and "risk_verdict" not in payload:
            raise ValueError("missing risk_verdict")

    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg, payload_validator=validator)
    with pytest.raises(ValueError, match="risk_verdict"):
        asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
    assert bridge.metrics.schema_violations == 1
    assert bridge.metrics.publish_errors == 1
    assert "object.verdict" not in provider._records
    # A valid record passes.
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload(risk_verdict="auto")))
    assert bridge.metrics.published == 1


def test_bridge_handler_timeout_dead_letters_stuck_handler() -> None:
    """A handler that never returns is bounded and dead-lettered, keeping the
    consumer making progress."""
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg, handler_timeout=0.01)

    async def stuck(_t: str, _p: dict) -> None:
        await asyncio.sleep(10)

    bridge.subscribe("object.verdict", "Thor", stuck)
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))

    async def _go() -> None:
        run_task = asyncio.create_task(bridge.run())
        await asyncio.sleep(0.1)  # let the 10ms handler timeout fire
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_go())
    assert bridge.metrics.handler_errors == 1
    assert bridge.metrics.dead_lettered == 1


def test_bridge_redrive_reprocesses_dead_letters() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def boom(_t: str, _p: dict) -> None:
        raise RuntimeError("transient outage")

    bridge.subscribe("object.verdict", "Thor", boom)
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload(risk_verdict="auto")))
    _drain(bridge)
    assert bridge.metrics.dead_lettered == 1

    # Root cause fixed: redrive with a working handler.
    got: list[dict] = []

    async def good(_t: str, p: dict) -> None:
        got.append(p)

    result = asyncio.run(bridge.redrive("object.verdict", good))
    assert result == {"redriven": 1, "failed": 0}
    assert got[0]["risk_verdict"] == "auto"  # original payload unwrapped


def test_bridge_redrive_reparks_still_failing_record() -> None:
    reg = load_pantheon()
    provider = InMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=reg)

    async def boom(_t: str, _p: dict) -> None:
        raise RuntimeError("still broken")

    bridge.subscribe("object.verdict", "Thor", boom)
    asyncio.run(bridge.publish("Forseti", "object.verdict", _verdict_payload()))
    _drain(bridge)

    result = asyncio.run(bridge.redrive("object.verdict", boom))
    assert result == {"redriven": 0, "failed": 1}
    # Re-parked, not lost: a second .dlq record now exists.
    assert len(provider._records["object.verdict.dlq"]) == 2


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
        await bridge.publish("Huginn", "object.event", _event_payload(event_type="e"))
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
    terminal: list[tuple[str, str, str]] = []
    bridge.consumer_state_observer = lambda agent, topic, state: terminal.append(
        (agent, topic, state)
    )

    async def handler(_t: str, _p: dict) -> None:  # pragma: no cover - never reached
        return None

    bridge.subscribe("object.event", "Heimdall", handler)
    asyncio.run(_spin(bridge))
    assert bridge.metrics.consumers_restarted == 3
    assert bridge.metrics.consumers_crashed == 4  # 3 restarts + final give-up
    snapshot = bridge.snapshot()
    assert snapshot["status"] == "degraded"
    assert snapshot["unavailable_agents"] == ["Heimdall"]
    assert snapshot["consumer_states"]["Heimdall:object.event"] == "gave_up"
    assert terminal == [("Heimdall", "object.event", "gave_up")]


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


def test_stop_drains_stream_cleanup_that_crosses_first_timeout() -> None:
    class _SlowClosingStream:
        def __init__(self) -> None:
            self.closed = False

        def __aiter__(self):  # noqa: ANN204 - minimal async iterator test double
            return self

        async def __anext__(self):  # noqa: ANN204 - minimal async iterator test double
            await asyncio.Future()

        async def aclose(self) -> None:
            await asyncio.sleep(0.075)
            self.closed = True

    class _SlowClosingBus(InMemoryEventBus):
        def __init__(self) -> None:
            super().__init__()
            self.stream = _SlowClosingStream()

        def subscribe(self, topic: str, group_id: str):  # type: ignore[override]
            del topic, group_id
            return self.stream

    provider = _SlowClosingBus()
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        shutdown_timeout=0.05,
    )

    async def handler(_topic: str, _payload: dict) -> None:
        return None

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        for _ in range(5):
            await asyncio.sleep(0)
        await bridge.stop()
        await run_task

    asyncio.run(_drive())

    assert provider.stream.closed is True
    assert bridge._tasks == []


# ---------------------------------------------------------------------------
# StateStoreAuditChainAdapter
# ---------------------------------------------------------------------------


async def _append_saga_entry(
    chain: StateStoreAuditChainAdapter, correlation_id: str = "shared"
) -> AuditEntry:
    return await chain.append(
        principal="Saga", topic="object.audit-entry", correlation_id=correlation_id, payload={}
    )


async def test_state_store_audit_chain_retries_overlapping_replicas() -> None:
    class _RacingStore(InMemoryStateStore):
        async def read_state(self, key: str) -> Mapping[str, object] | None:
            result = await super().read_state(key)
            await asyncio.sleep(0)
            return result

    store = _RacingStore()
    first, second = StateStoreAuditChainAdapter(store), StateStoreAuditChainAdapter(store)
    for index in range(10):
        results = await asyncio.gather(
            _append_saga_entry(first, f"first-{index}"),
            _append_saga_entry(second, f"second-{index}"),
        )
        assert sorted(entry.seq for entry in results) == [index * 2, index * 2 + 1]
    restarted = StateStoreAuditChainAdapter(store)
    assert (await _append_saga_entry(restarted)).seq == 20
    restarted.verify()
    assert await store.verify_chain()


async def test_state_store_audit_chain_failed_transaction_preserves_head_and_mirror() -> None:
    class _FailingStore(InMemoryStateStore):
        fail_audit = False

        def _append_audit_locked(self, entry: Mapping[str, object]) -> None:
            super()._append_audit_locked(entry)
            if self.fail_audit:
                raise RuntimeError("injected audit transaction failure")

    store = _FailingStore()
    chain = StateStoreAuditChainAdapter(store)
    original = await _append_saga_entry(chain)
    head_before = await store.read_state(AUDIT_CHECKPOINT_KEY)
    rows_before = tuple(store.audit_entries)
    store.fail_audit = True
    with pytest.raises(RuntimeError, match="injected audit transaction failure"):
        await _append_saga_entry(chain, "failed")
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) == head_before
    assert tuple(store.audit_entries) == rows_before
    assert chain.entries == [original]
    store.fail_audit = False
    assert (await _append_saga_entry(StateStoreAuditChainAdapter(store))).seq == 1


async def test_state_store_audit_chain_cancellation_does_not_expose_uncommitted_entry() -> None:
    class _BlockedStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def compare_and_set_state_with_audit(self, *args, **kwargs) -> bool:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("blocked transaction must be canceled")

    store = _BlockedStore()
    chain = StateStoreAuditChainAdapter(store)
    task = asyncio.create_task(_append_saga_entry(chain))
    await store.started.wait()
    head_before = await store.read_state(AUDIT_CHECKPOINT_KEY)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert chain.entries == []
    assert tuple(store.audit_entries) == ()
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) == head_before


async def test_state_store_audit_chain_conflict_budget_holds_without_local_fallback() -> None:
    class _ConflictedStore(InMemoryStateStore):
        attempts = 0

        async def compare_and_set_state_with_audit(self, *args, **kwargs) -> bool:
            self.attempts += 1
            return False

    store = _ConflictedStore()
    chain = StateStoreAuditChainAdapter(store)
    with pytest.raises(AuditChainError, match="contention budget exhausted"):
        await _append_saga_entry(chain)
    assert store.attempts == 8
    assert chain.entries == []
    assert tuple(store.audit_entries) == ()


async def test_state_store_audit_chain_deadline_holds_without_local_fallback(monkeypatch) -> None:
    monkeypatch.setattr(audit_chain_rehydrate, "_APPEND_DEADLINE_SECONDS", 0.01)
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store)
    await chain._append_lock.acquire()  # noqa: SLF001 - hold the exact bounded admission seam.
    try:
        with pytest.raises(AuditChainError, match="deadline exceeded"):
            await _append_saga_entry(chain)
        assert chain.entries == []
        assert tuple(store.audit_entries) == ()
    finally:
        chain._append_lock.release()  # noqa: SLF001


async def test_state_store_audit_chain_does_not_cancel_an_admitted_atomic_append(
    monkeypatch,
) -> None:
    class _SlowCommittedStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def compare_and_set_state_with_audit(self, *args, **kwargs) -> bool:
            self.started.set()
            await self.release.wait()
            return await super().compare_and_set_state_with_audit(*args, **kwargs)

    monkeypatch.setattr(audit_chain_rehydrate, "_APPEND_DEADLINE_SECONDS", 0.01)
    store = _SlowCommittedStore()
    chain = StateStoreAuditChainAdapter(store)
    task = asyncio.create_task(_append_saga_entry(chain))
    await store.started.wait()
    await asyncio.sleep(0.02)
    store.release.set()

    entry = await task

    assert chain.entries == [entry]
    assert len(tuple(store.audit_entries)) == 1


async def test_state_store_audit_chain_byte_budget_holds_without_head_advance() -> None:
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store)
    original = await _append_saga_entry(chain)
    head_before = await store.read_state(AUDIT_CHECKPOINT_KEY)
    with pytest.raises(AuditChainError, match="byte budget"):
        await _append_saga_entry(chain, "x" * (512 * 1_024))
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) == head_before
    assert chain.entries == [original]
    assert len(tuple(store.audit_entries)) == 1


def test_state_store_audit_chain_byte_budget_includes_content_digest(monkeypatch) -> None:
    journal = audit_chain_journal.AuditJournal(1, 0, "0" * 64, ())
    stored = journal.encode()
    body = {key: value for key, value in stored.items() if key != "content_digest"}
    monkeypatch.setattr(audit_chain_journal, "_JOURNAL_BYTE_LIMIT", len(json.dumps(body).encode()))
    with pytest.raises(AuditChainError, match="byte budget"):
        journal.encode()


@pytest.mark.parametrize("limit", [0, 513, True, "1"])
async def test_state_store_audit_reader_rejects_invalid_limits(limit) -> None:
    with pytest.raises(ValueError, match="limit must be"):
        await InMemoryStateStore().read_audit_entries(limit=limit)


@pytest.mark.parametrize("corruption", ["revision", "base_length", "sequence", "digest", "extra"])
async def test_state_store_audit_chain_rejects_tampered_shared_journal(corruption: str) -> None:
    store = InMemoryStateStore()
    original = StateStoreAuditChainAdapter(store)
    await _append_saga_entry(original)
    stored = dict(await store.read_state(AUDIT_CHECKPOINT_KEY))
    if corruption in {"revision", "base_length"}:
        stored[corruption] = True
    elif corruption == "sequence":
        stored["entries"][0]["seq"] = True
    elif corruption == "digest":
        stored["content_digest"] = "f" * 64
    else:
        stored["unreviewed"] = True
    await store.write_state(AUDIT_CHECKPOINT_KEY, stored)
    rows_before = tuple(store.audit_entries)
    restarted = StateStoreAuditChainAdapter(store)
    with pytest.raises(AuditChainError):
        await _append_saga_entry(restarted)
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) == stored
    assert tuple(store.audit_entries) == rows_before
    assert restarted.entries == []


@pytest.mark.parametrize("checkpoint", [False, True])
@pytest.mark.parametrize("legacy_hash", [False, True])
async def test_state_store_audit_chain_migrates_complete_legacy_history(
    checkpoint: bool, legacy_hash: bool
) -> None:
    store = InMemoryStateStore()
    await store.append_audit_entry({"action_kind": "unrelated.record"})
    entry = AuditEntry(
        seq=0,
        prev_hash="0" * 64,
        entry_hash="",
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="legacy",
        payload_digest=_digest({}),
    )
    entry = replace(entry, entry_hash=entry_hash(entry, legacy=legacy_hash))
    await store.append_audit_entry(
        {**asdict(entry), "actor": "Saga", "action_kind": "audit.record", "payload": {}}
    )
    if checkpoint:
        await store.write_state(
            AUDIT_CHECKPOINT_KEY,
            {"schema_version": "1.0.0", "length": 1, "head_hash": entry.entry_hash},
        )
    rows_before = tuple(store.audit_entries)
    restarted = StateStoreAuditChainAdapter(store)
    appended = await _append_saga_entry(restarted)
    assert appended.seq == 1
    assert appended.prev_hash == entry.entry_hash
    assert tuple(store.audit_entries)[:2] == rows_before
    assert len(tuple(store.audit_entries)) == 3
    restarted.verify(full=True)


async def test_state_store_audit_chain_holds_when_legacy_reader_is_missing(monkeypatch) -> None:
    store = InMemoryStateStore()
    monkeypatch.delattr(InMemoryStateStore, "read_audit_entries")
    monkeypatch.delattr(InMemoryStateStore, "read_audit_chain_entries")
    with pytest.raises(AuditChainError, match="history reader is required"):
        await _append_saga_entry(StateStoreAuditChainAdapter(store))
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) is None
    assert tuple(store.audit_entries) == ()


async def test_state_store_audit_chain_starts_when_unrelated_audit_rows_exceed_the_bound() -> None:
    # Every component writes the same audit table, so a fresh runtime can pass the migration
    # bound with other writers' rows before Saga records its first entry.
    store = InMemoryStateStore()
    for index in range(600):
        await store.append_audit_entry({"action_kind": "unrelated.record", "index": index})
    appended = await _append_saga_entry(StateStoreAuditChainAdapter(store))
    assert appended.seq == 0 and appended.prev_hash == "0" * 64
    assert (await store.read_state(AUDIT_CHECKPOINT_KEY)) is not None
    assert len(tuple(store.audit_entries)) == 601


async def test_state_store_audit_chain_reader_counts_only_chain_records() -> None:
    store = InMemoryStateStore()
    for index in range(513):
        await store.append_audit_entry({"action_kind": "unrelated.record", "index": index})
    await store.append_audit_entry({"actor": "Saga", "action_kind": "audit.record"})
    await store.append_audit_entry({"actor": "Other", "action_kind": "audit.record"})
    records, truncated = await store.read_audit_chain_entries(limit=512)
    assert len(records) == 1 and truncated is False
    assert is_audit_chain_record(records[0])
    assert not is_audit_chain_record({"actor": "Other", "action_kind": "audit.record"})


def test_audit_chain_record_fields_match_the_journal_entry_fields() -> None:
    assert AUDIT_CHAIN_ENTRY_FIELDS == audit_chain_journal._ENTRY_FIELDS


async def test_state_store_audit_chain_holds_incomplete_legacy_history() -> None:
    store = InMemoryStateStore()
    for _ in range(513):
        await store.append_audit_entry({"actor": "Saga", "action_kind": "audit.record"})
    rows_before = tuple(store.audit_entries)
    with pytest.raises(AuditChainError, match="bounded migration"):
        await _append_saga_entry(StateStoreAuditChainAdapter(store))
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) is None
    assert tuple(store.audit_entries) == rows_before


async def test_state_store_audit_chain_rejects_legacy_checkpoint_without_matching_history() -> None:
    store = InMemoryStateStore()
    checkpoint = {"schema_version": "1.0.0", "length": 1, "head_hash": "a" * 64}
    await store.write_state(AUDIT_CHECKPOINT_KEY, checkpoint)
    with pytest.raises(AuditChainError, match="inconsistent with complete legacy history"):
        await _append_saga_entry(StateStoreAuditChainAdapter(store))
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) == checkpoint
    assert tuple(store.audit_entries) == ()


@pytest.mark.parametrize("corruption", ["sequence_type", "sequence_gap", "payload"])
async def test_state_store_audit_chain_holds_corrupted_legacy_history(corruption: str) -> None:
    seed = InMemoryStateStore()
    entry = await _append_saga_entry(StateStoreAuditChainAdapter(seed))
    record = dict(next(iter(seed.audit_entries))["entry"])
    if corruption == "sequence_type":
        record["seq"] = True
    elif corruption == "sequence_gap":
        changed = replace(entry, seq=1)
        record.update(asdict(replace(changed, entry_hash=entry_hash(changed))))
    else:
        record["payload"] = {"tampered": True}
    store = InMemoryStateStore()
    await store.append_audit_entry(record)
    rows_before = tuple(store.audit_entries)
    assert await store.verify_chain()
    with pytest.raises(AuditChainError):
        await _append_saga_entry(StateStoreAuditChainAdapter(store))
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) is None
    assert tuple(store.audit_entries) == rows_before


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
    stored = [row["entry"] for row in store.audit_entries]
    assert [row["actor"] for row in stored] == ["Saga", "Saga"]
    assert [row["action_kind"] for row in stored] == ["audit.record", "audit.record"]
    assert [row["principal"] for row in stored] == ["Forseti", "Thor"]
    assert [row["payload"] for row in stored] == [
        {"risk_verdict": "auto"},
        {"state": "succeeded"},
    ]


def test_state_store_audit_chain_exposes_entry_only_after_durable_append() -> None:
    class _BlockedStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.append_started = asyncio.Event()
            self.release_append = asyncio.Event()

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: Mapping[str, object],
            *,
            expected_revision: int,
            audit_entry: Mapping[str, object],
        ) -> bool:
            self.append_started.set()
            await self.release_append.wait()
            return await super().compare_and_set_state_with_audit(
                key, value, expected_revision=expected_revision, audit_entry=audit_entry
            )

    async def _exercise() -> None:
        store = _BlockedStore()
        chain = StateStoreAuditChainAdapter(store=store)
        task = asyncio.create_task(
            chain.append(
                principal="Mimir",
                topic="object.rule",
                correlation_id="catalog-review",
                payload={"state": "terminal"},
            )
        )
        await store.append_started.wait()
        assert chain.entries == []
        store.release_append.set()
        await task
        assert len(chain.entries) == 1
        chain.verify()

    asyncio.run(_exercise())


def test_state_store_audit_chain_serializes_concurrent_appends() -> None:
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store=store)

    async def _exercise() -> None:
        await asyncio.gather(
            *(
                chain.append(
                    principal="Saga",
                    topic="object.audit-entry",
                    correlation_id=f"c-{index}",
                    payload={"index": index},
                )
                for index in range(20)
            )
        )

    asyncio.run(_exercise())
    chain.verify()
    assert [entry.seq for entry in chain.entries] == list(range(20))
    assert len({entry.entry_hash for entry in chain.entries}) == 20


def test_state_store_audit_chain_serializes_alternating_replicas() -> None:
    async def _exercise() -> None:
        store = InMemoryStateStore()
        first = StateStoreAuditChainAdapter(store=store)
        second = StateStoreAuditChainAdapter(store=store)
        appended = []
        for index, adapter in enumerate((first, second, first)):
            appended.append(
                await adapter.append(
                    principal="Saga",
                    topic="object.audit-entry",
                    correlation_id=f"replica-{index}",
                    payload={"index": index},
                )
            )
        assert [entry.seq for entry in appended] == [0, 1, 2]
        assert appended[2].prev_hash == appended[1].entry_hash
        restarted = StateStoreAuditChainAdapter(store=store)
        resumed = await restarted.append(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id="replica-restart",
            payload={},
        )
        assert resumed.seq == 3
        assert resumed.prev_hash == appended[2].entry_hash
        restarted.verify()

    asyncio.run(_exercise())


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


def test_state_store_audit_chain_keeps_unknown_source_distinct_from_saga_actor() -> None:
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store=store)

    asyncio.run(
        chain.append(
            principal="unknown",
            topic="object.verdict",
            correlation_id="c",
            payload={"risk_verdict": "deny"},
        )
    )

    stored = next(iter(store.audit_entries))["entry"]
    assert stored["actor"] == "Saga"
    assert stored["principal"] == "unknown"


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
    assert verdict["risk_verdict"] == "hil"
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
        await bus.publish(
            "Forseti",
            "object.arbitration-request",
            {
                "correlation_id": "arbitration:vm-1",
                "idempotency_key": "arbitration-request:vm-1",
                "resource_id": "vm-1",
            },
        )

    asyncio.run(_run())
    assert "injected" not in observed  # second subscriber saw a clean copy


def test_bridge_metrics_expose_consumers_gave_up() -> None:
    # H10: a permanently-dead subscription is observable via a dedicated
    # counter, not silently folded into consumers_crashed.
    from fdai.agents._framework.bus_bridge import BridgeMetrics

    snap = BridgeMetrics().as_dict()
    assert snap["consumers_gave_up"] == 0
