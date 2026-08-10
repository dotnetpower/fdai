from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.agents import Forseti, Vidar
from fdai.core.ontology_platform.reconciliation import ReconciliationPublicationStatus
from fdai.runtime.reconciliation_outbox import (
    RECONCILIATION_DECISION_TOPIC,
    RECONCILIATION_RECOVERY_TOPIC,
    ReconciliationOutboxPublisher,
    build_reconciliation_runtime,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing import InMemoryEventBus, InMemoryStateStore
from tests.core.ontology_platform.test_reconciliation import (
    _authenticated_context,
    _fixture,
    _request,
)

_NOW = datetime(2026, 8, 10, tzinfo=UTC)


async def _first(bus: InMemoryEventBus, topic: str):  # type: ignore[no-untyped-def]
    async for envelope in bus.subscribe(topic, "test-reader"):
        return envelope
    return None


async def test_runtime_publishes_matched_recommendation_to_forseti_without_authority() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    runtime = build_reconciliation_runtime(
        state_store=store,
        event_bus=bus,
        clock=lambda: _NOW,
    )
    outcome = await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    assert await runtime.publisher.run_once() == 1
    envelope = await _first(bus, RECONCILIATION_DECISION_TOPIC)
    assert envelope is not None
    assert envelope.key == outcome.recommendation.idempotency_key
    assert envelope.payload["proposal_only"] is True
    assert envelope.payload["grants_authority"] is False

    forseti = Forseti()
    await forseti.on_typed_message(envelope.topic, dict(envelope.payload))
    await forseti.on_typed_message(envelope.topic, dict(envelope.payload))
    assert forseti.behavior_snapshot()["reconciliation_recommendation:accepted"] == 1
    assert forseti.behavior_snapshot()["reconciliation_recommendation:duplicate"] == 1


async def test_runtime_routes_mismatch_to_vidar_as_proposal_without_rollback() -> None:
    release, target, plan, action_type = _fixture(action_type_name="ops.scale-out")
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        replicas=4,
    )
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    runtime = build_reconciliation_runtime(
        state_store=store,
        event_bus=bus,
        clock=lambda: _NOW,
    )
    outcome = await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    assert await runtime.publisher.run_once() == 1
    envelope = await _first(bus, RECONCILIATION_RECOVERY_TOPIC)
    assert envelope is not None
    assert envelope.payload["target_agent"] == "vidar"
    assert envelope.payload["action_type_ref"]["name"] == "ops.scale-out"
    vidar = Vidar(bus=None)
    await vidar.on_typed_message(envelope.topic, dict(envelope.payload))
    await vidar.on_typed_message(envelope.topic, dict(envelope.payload))

    assert vidar.records == []
    assert vidar.behavior_snapshot()["reconciliation_recovery:proposal_received"] == 1
    assert vidar.behavior_snapshot()["reconciliation_recovery:duplicate"] == 1
    facts = (await vidar.introspect("recovery", {})).facts
    assert facts["recovery_recommendations_pending"] == 1
    assert outcome.recommendation.grants_authority is False


async def test_publish_failure_releases_lease_and_restart_replays() -> None:
    class _FailOnceBus(InMemoryEventBus):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def publish(self, topic, key, payload):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise RuntimeError("broker unavailable")
            return await super().publish(topic, key, payload)

    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    bus = _FailOnceBus()
    runtime = build_reconciliation_runtime(
        state_store=store,
        event_bus=bus,
        clock=lambda: _NOW,
    )
    await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    assert await runtime.publisher.run_once() == 0
    delayed = await runtime.ledger.claim_publications(
        now=_NOW + timedelta(seconds=29),
        limit=1,
        lease_until=_NOW + timedelta(seconds=59),
    )
    assert delayed == ()

    restarted = ReconciliationOutboxPublisher(
        ledger=runtime.ledger,
        event_bus=bus,
        clock=lambda: _NOW + timedelta(seconds=30),
    )
    assert await restarted.run_once() == 1
    assert await _first(bus, RECONCILIATION_DECISION_TOPIC) is not None


async def test_poison_publication_dead_letters_without_deleting_terminal_outcome() -> None:
    class _PoisonBus(InMemoryEventBus):
        async def publish(self, topic, key, payload):  # type: ignore[no-untyped-def]
            return PublishReceipt(topic=topic, partition=-1, offset=0)

    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    bus = _PoisonBus()
    runtime = build_reconciliation_runtime(
        state_store=store,
        event_bus=bus,
        clock=lambda: _NOW,
    )
    outcome = await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    assert await runtime.publisher.run_once() == 0
    record = await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}")
    assert record is not None
    assert record["terminal_outcome"] == outcome.model_dump(mode="json")
    publication = next(iter(record["publication_state"].values()))
    assert publication["status"] == ReconciliationPublicationStatus.FAILED.value
    assert await _first(bus, f"{RECONCILIATION_DECISION_TOPIC}.dlq") is not None


async def test_publisher_run_loop_drains_and_stops_cleanly() -> None:
    stop = asyncio.Event()

    class _StopAfterPublishBus(InMemoryEventBus):
        async def publish(self, topic, key, payload):  # type: ignore[no-untyped-def]
            receipt = await super().publish(topic, key, payload)
            stop.set()
            return receipt

    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    bus = _StopAfterPublishBus()
    runtime = build_reconciliation_runtime(
        state_store=InMemoryStateStore(),
        event_bus=bus,
        clock=lambda: _NOW,
    )
    await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    await asyncio.wait_for(runtime.publisher.run(stop), timeout=1.0)

    assert await _first(bus, RECONCILIATION_DECISION_TOPIC) is not None


async def test_publish_timeout_releases_current_lease_for_retry() -> None:
    class _BlockedBus(InMemoryEventBus):
        async def publish(self, topic, key, payload):  # type: ignore[no-untyped-def]
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    runtime = build_reconciliation_runtime(
        state_store=store,
        event_bus=_BlockedBus(),
        clock=lambda: _NOW,
    )
    runtime = replace(
        runtime,
        publisher=ReconciliationOutboxPublisher(
            ledger=runtime.ledger,
            event_bus=_BlockedBus(),
            clock=lambda: _NOW,
            publish_timeout_seconds=0.1,
        ),
    )
    await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    assert await runtime.publisher.run_once() == 0
    record = await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}")
    assert record is not None
    publication = next(iter(record["publication_state"].values()))
    assert publication["status"] == "pending"
    assert "lease_token" not in publication
    assert publication["lease_token_hash"] is None
    assert publication["last_error"] == "TimeoutError"


async def test_dead_letter_failure_releases_publication_instead_of_stranding_lease() -> None:
    class _PoisonAndFailingDlqBus(InMemoryEventBus):
        async def publish(self, topic, key, payload):  # type: ignore[no-untyped-def]
            return PublishReceipt(topic=topic, partition=-1, offset=0)

        async def dead_letter(self, topic, key, payload, reason):  # type: ignore[no-untyped-def]
            raise RuntimeError("DLQ unavailable")

    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    store = InMemoryStateStore()
    runtime = build_reconciliation_runtime(
        state_store=store,
        event_bus=_PoisonAndFailingDlqBus(),
        clock=lambda: _NOW,
    )
    await runtime.coordinator.coordinate(
        request,
        observation_context=_authenticated_context(request),
        active_release=release,
    )

    assert await runtime.publisher.run_once() == 0
    record = await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}")
    assert record is not None
    publication = next(iter(record["publication_state"].values()))
    assert publication["status"] == "pending"
    assert "lease_token" not in publication
    assert publication["lease_token_hash"] is None
    assert publication["last_error"] == "RuntimeError"
