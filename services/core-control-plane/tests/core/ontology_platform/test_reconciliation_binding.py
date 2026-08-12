"""Production binder tests for reconciliation event, provider, and outbox boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    StateStoreReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_binding import (
    RECONCILIATION_OUTBOX_TOPIC,
    EffectReconciliationBinder,
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_events import (
    EffectReconciliationRequestEvent,
    ReconciliationOutboxDeliveryState,
    ReconciliationOutboxEvent,
    ReconciliationOutboxRecord,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.ontology_platform.test_reconciliation import (
    CREATED_AT,
    _authenticated_context,
    _fixture,
    _request,
)


class _StaticArtifactResolver:
    def __init__(self, artifacts: ResolvedReconciliationArtifacts) -> None:
        self.artifacts = artifacts
        self.calls = 0

    async def resolve(self, event: EffectReconciliationRequestEvent):
        del event
        self.calls += 1
        return self.artifacts


class _ExactObservationVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(self, *, evidence, claimed_context):
        if evidence.observation_id != claimed_context.verification_receipt.observation_id:
            raise ValueError("observation verification receipt binds another observation")
        self.calls += 1
        return claimed_context


class _SubstitutingObservationVerifier:
    async def verify(self, *, evidence, claimed_context):
        del evidence
        return claimed_context.model_copy(
            update={"source_credential_lineage": "credential:substituted:1"}
        )


class _FailOnceEventBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("synthetic broker failure")
        return await super().publish(topic, key, payload)


def _binder(*, store, bus, artifacts, verifier, claimant_id):
    ledger = StateStoreReconciliationLedger(store=store)
    return EffectReconciliationBinder(
        coordinator=EffectReconciliationCoordinator(ledger=ledger),
        ledger=ledger,
        event_bus=bus,
        artifact_resolver=artifacts,
        observation_verifier=verifier,
        claimant_id=claimant_id,
    )


async def test_duplicate_reorder_and_restart_publish_one_stable_outbox_event() -> None:
    release, target, plan, action_type = _fixture()
    matched = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    reordered = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        replicas=4,
        observed_at=CREATED_AT + timedelta(minutes=1, seconds=1),
    )
    matched_event = EffectReconciliationRequestEvent.from_request(
        matched,
        observation_context=_authenticated_context(matched),
    )
    reordered_event = EffectReconciliationRequestEvent.from_request(
        reordered,
        observation_context=_authenticated_context(reordered),
    )
    artifacts = _StaticArtifactResolver(
        ResolvedReconciliationArtifacts(
            plan=plan,
            action_type=action_type,
            active_release=release,
        )
    )
    verifier = _ExactObservationVerifier()
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    first_binder = _binder(
        store=store,
        bus=bus,
        artifacts=artifacts,
        verifier=verifier,
        claimant_id="reconciliation-drainer-before-restart",
    )

    first = await first_binder.handle_event(matched_event.model_dump(mode="json"))
    duplicate = await first_binder.handle_event(matched_event.model_dump(mode="json"))
    late = await first_binder.handle_event(reordered_event.model_dump(mode="json"))
    restarted = _binder(
        store=store,
        bus=bus,
        artifacts=artifacts,
        verifier=verifier,
        claimant_id="reconciliation-drainer-after-restart",
    )
    now = CREATED_AT + timedelta(minutes=3)
    published = await restarted.publish_pending(now=now)
    no_second_publication = await restarted.publish_pending(now=now)

    records = tuple(
        [event async for event in bus.subscribe(RECONCILIATION_OUTBOX_TOPIC, "assertion-group")]
    )
    final_duplicate = await restarted.handle_event(reordered_event.model_dump(mode="json"))
    final_drain = await restarted.drain_pending(now=now + timedelta(minutes=1))

    assert duplicate == first
    assert late == first
    assert final_duplicate == first
    assert published == ReconciliationOutboxEvent.from_outcome(first)
    assert no_second_publication is None
    assert final_drain == ()
    assert len(records) == 1
    assert records[0].key == first.reconciliation_id
    assert ReconciliationOutboxEvent.model_validate(records[0].payload) == published
    aggregate = await store.read_state(f"ontology:reconciliation:{first.reconciliation_id}")
    assert aggregate is not None
    delivery = ReconciliationOutboxRecord.model_validate(
        aggregate["outbox"][published.idempotency_key]
    )
    assert delivery.state is ReconciliationOutboxDeliveryState.PUBLISHED
    assert delivery.attempts == 1
    assert artifacts.calls == 4
    assert verifier.calls == 4


async def test_binder_rejects_substituted_authenticated_context_before_persistence() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    request_event = EffectReconciliationRequestEvent.from_request(
        request,
        observation_context=_authenticated_context(request),
    )
    store = InMemoryStateStore()
    artifacts = _StaticArtifactResolver(
        ResolvedReconciliationArtifacts(
            plan=plan,
            action_type=action_type,
            active_release=release,
        )
    )
    binder = _binder(
        store=store,
        bus=InMemoryEventBus(),
        artifacts=artifacts,
        verifier=_SubstitutingObservationVerifier(),
        claimant_id="reconciliation-drainer",
    )

    with pytest.raises(ValueError, match="verified observation context does not match"):
        await binder.handle_event(request_event.model_dump(mode="json"))

    assert artifacts.calls == 0
    assert await store.read_state(f"ontology:reconciliation:{request.reconciliation_id}") is None


async def test_broker_failure_releases_same_outbox_event_for_restart_retry() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    request_event = EffectReconciliationRequestEvent.from_request(
        request,
        observation_context=_authenticated_context(request),
    )
    artifacts = _StaticArtifactResolver(
        ResolvedReconciliationArtifacts(
            plan=plan,
            action_type=action_type,
            active_release=release,
        )
    )
    store = InMemoryStateStore()
    bus = _FailOnceEventBus()
    binder = _binder(
        store=store,
        bus=bus,
        artifacts=artifacts,
        verifier=_ExactObservationVerifier(),
        claimant_id="reconciliation-drainer-before-failure",
    )
    outcome = await binder.handle_event(request_event.model_dump(mode="json"))
    now = CREATED_AT + timedelta(minutes=3)

    with pytest.raises(RuntimeError, match="synthetic broker failure"):
        await binder.publish_pending(now=now)

    restarted = _binder(
        store=store,
        bus=bus,
        artifacts=artifacts,
        verifier=_ExactObservationVerifier(),
        claimant_id="reconciliation-drainer-after-failure",
    )
    assert await restarted.publish_pending(now=now + timedelta(seconds=4)) is None
    published = await restarted.publish_pending(now=now + timedelta(seconds=5))
    records = tuple(
        [event async for event in bus.subscribe(RECONCILIATION_OUTBOX_TOPIC, "retry-group")]
    )

    assert published is not None
    assert published.idempotency_key == outcome.recommendation.idempotency_key
    assert len(records) == 1
    aggregate = await store.read_state(f"ontology:reconciliation:{outcome.reconciliation_id}")
    assert aggregate is not None
    delivery = ReconciliationOutboxRecord.model_validate(
        aggregate["outbox"][published.idempotency_key]
    )
    assert delivery.state is ReconciliationOutboxDeliveryState.PUBLISHED
    assert delivery.event == published
    assert delivery.attempts == 2
