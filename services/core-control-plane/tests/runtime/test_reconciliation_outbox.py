from __future__ import annotations

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
    release, target, plan, action_type = _fixture()
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
