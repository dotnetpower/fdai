"""Focused tests for the bounded effect reconciliation runtime worker."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    StateStoreReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_binding import (
    RECONCILIATION_OUTBOX_TOPIC,
    RECONCILIATION_REQUEST_TOPIC,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectObservationEnvelope,
    reconciliation_content_digest,
)
from fdai.core.ontology_platform.reconciliation_events import (
    EffectReconciliationRequestEvent,
    ReconciliationOutboxDeliveryState,
    ReconciliationOutboxEvent,
    ReconciliationOutboxRecord,
)
from fdai.delivery.reconciliation import (
    IndependentObservationContextVerifier,
    LocalReconciliationArtifactResolver,
)
from fdai.delivery.reconciliation_runtime import EffectReconciliationWorker
from fdai.shared.contracts.models import OntologyActionType, OntologyRelease
from fdai.shared.providers.event_bus import EventBus, PublishReceipt
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.ontology_platform.test_reconciliation import (
    CREATED_AT,
    _authenticated_context,
    _fixture,
    _request,
)

_WATCHDOG_SECONDS = 0.5


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class _Authenticator:
    async def authenticate(
        self,
        *,
        evidence: EffectObservationEnvelope,
        claimed_context: AuthenticatedObservationContext,
    ) -> AuthenticatedObservationContext:
        del evidence
        return claimed_context


class _BlockingAuthenticator(_Authenticator):
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def authenticate(
        self,
        *,
        evidence: EffectObservationEnvelope,
        claimed_context: AuthenticatedObservationContext,
    ) -> AuthenticatedObservationContext:
        del evidence, claimed_context
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _BlockingPublishEventBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.block_outbox = True
        self.outbox_publish_attempts = 0
        self.entered = asyncio.Event()

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if topic == RECONCILIATION_OUTBOX_TOPIC:
            self.outbox_publish_attempts += 1
            if self.block_outbox:
                self.entered.set()
                await asyncio.Event().wait()
        return await super().publish(topic, key, payload)


@dataclass(frozen=True, slots=True)
class _Harness:
    worker: EffectReconciliationWorker
    ledger: StateStoreReconciliationLedger
    event: EffectReconciliationRequestEvent
    release: OntologyRelease
    target: OntologyObjectRecord
    plan: Any
    action_type: OntologyActionType
    store: InMemoryStateStore
    event_bus: EventBus
    clock: _FakeClock


def _harness(
    *,
    store: InMemoryStateStore | None = None,
    event_bus: EventBus | None = None,
    clock: _FakeClock | None = None,
    claimant_id: str = "reconciliation-runtime",
    group_id: str = "reconciliation-runtime-group",
    authenticator: _Authenticator | None = None,
    event_handling_timeout_seconds: float = 5.0,
    publish_timeout_seconds: float = 2.0,
) -> _Harness:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    context = _authenticated_context(request)
    event = EffectReconciliationRequestEvent.from_request(
        request,
        observation_context=context,
    )
    runtime_store = store or InMemoryStateStore()
    runtime_event_bus = event_bus or InMemoryEventBus()
    runtime_clock = clock or _FakeClock(CREATED_AT + timedelta(minutes=3))
    ledger = StateStoreReconciliationLedger(store=runtime_store)
    resolver = LocalReconciliationArtifactResolver(
        active_release=release,
        action_types=(action_type,),
        plans=(plan,),
        target_reader=_TargetReader(target),
    )
    verifier = IndependentObservationContextVerifier(
        authenticator=authenticator or _Authenticator()
    )
    worker = EffectReconciliationWorker(
        coordinator=EffectReconciliationCoordinator(ledger=ledger),
        ledger=ledger,
        event_bus=runtime_event_bus,
        artifact_resolver=resolver,
        observation_verifier=verifier,
        claimant_id=claimant_id,
        group_id=group_id,
        clock=runtime_clock,
        event_handling_timeout_seconds=event_handling_timeout_seconds,
        publish_timeout_seconds=publish_timeout_seconds,
    )
    return _Harness(
        worker=worker,
        ledger=ledger,
        event=event,
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        store=runtime_store,
        event_bus=runtime_event_bus,
        clock=runtime_clock,
    )


class _TargetReader:
    def __init__(self, target: OntologyObjectRecord) -> None:
        self._target = target

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        assert object_id == self._target.id
        return self._target


async def test_subscriber_duplicate_restart_and_conflicting_replay_are_stable() -> None:
    harness = _harness()
    payload = harness.event.model_dump(mode="json")
    await harness.event_bus.publish(
        RECONCILIATION_REQUEST_TOPIC,
        harness.event.reconciliation_id,
        payload,
    )
    await harness.event_bus.publish(
        RECONCILIATION_REQUEST_TOPIC,
        harness.event.reconciliation_id,
        payload,
    )

    await asyncio.wait_for(harness.worker.run_subscriber(), timeout=_WATCHDOG_SECONDS)
    restarted = _harness(
        store=harness.store,
        event_bus=harness.event_bus,
        clock=harness.clock,
        claimant_id="reconciliation-runtime-restarted",
        group_id="reconciliation-runtime-group",
    )
    duplicate = await asyncio.wait_for(
        restarted.worker.handle_payload(payload),
        timeout=_WATCHDOG_SECONDS,
    )

    conflicting_request = _request(
        release=harness.release,
        target=harness.target,
        plan=harness.plan,
        action_type=harness.action_type,
        replicas=4,
        observed_at=CREATED_AT + timedelta(minutes=1, seconds=1),
    )
    conflicting_event = EffectReconciliationRequestEvent.from_request(
        conflicting_request,
        observation_context=_authenticated_context(conflicting_request),
    )
    conflicting_payload = conflicting_event.model_dump(mode="json")
    conflicting_payload["observation_attempt_id"] = harness.event.observation_attempt_id
    conflicting_payload["event_digest"] = reconciliation_content_digest(
        {key: value for key, value in conflicting_payload.items() if key != "event_digest"}
    )
    with pytest.raises(ValueError, match="identities do not match"):
        await asyncio.wait_for(
            restarted.worker.handle_payload(conflicting_payload),
            timeout=_WATCHDOG_SECONDS,
        )

    published = await asyncio.wait_for(
        restarted.worker.publish_pending_once(),
        timeout=_WATCHDOG_SECONDS,
    )
    assert published is not None
    assert published.proposal_only is True
    assert published.grants_authority is False
    assert published.result.reconciliation_id == duplicate.reconciliation_id
    records = tuple(
        [
            envelope
            async for envelope in harness.event_bus.subscribe(
                RECONCILIATION_OUTBOX_TOPIC,
                "reconciliation-runtime-assertion",
            )
        ]
    )
    assert len(records) == 1
    assert ReconciliationOutboxEvent.model_validate(records[0].payload) == published


async def test_publish_timeout_releases_pending_without_inline_retry() -> None:
    event_bus = _BlockingPublishEventBus()
    harness = _harness(event_bus=event_bus, publish_timeout_seconds=0.01)
    await harness.worker.handle_payload(harness.event.model_dump(mode="json"))

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            harness.worker.publish_pending_once(),
            timeout=_WATCHDOG_SECONDS,
        )

    aggregate = await harness.store.read_state(
        f"ontology:reconciliation:{harness.event.reconciliation_id}"
    )
    assert aggregate is not None
    delivery = ReconciliationOutboxRecord.model_validate(
        aggregate["outbox"][next(iter(aggregate["outbox"]))]
    )
    assert delivery.state is ReconciliationOutboxDeliveryState.PENDING
    assert delivery.attempts == 1
    assert delivery.available_at == harness.clock.now + timedelta(seconds=5)
    assert event_bus.outbox_publish_attempts == 1

    event_bus.block_outbox = False
    assert await harness.worker.publish_pending_once() is None
    harness.clock.advance(timedelta(seconds=5))
    assert await harness.worker.publish_pending_once() is not None
    assert event_bus.outbox_publish_attempts == 2


async def test_cancelled_publish_reclaims_default_lease_after_restart() -> None:
    event_bus = _BlockingPublishEventBus()
    harness = _harness(event_bus=event_bus)
    await harness.worker.handle_payload(harness.event.model_dump(mode="json"))

    publish_task = asyncio.create_task(harness.worker.publish_pending_once())
    await asyncio.wait_for(event_bus.entered.wait(), timeout=_WATCHDOG_SECONDS)
    publish_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(publish_task, timeout=_WATCHDOG_SECONDS)

    aggregate = await harness.store.read_state(
        f"ontology:reconciliation:{harness.event.reconciliation_id}"
    )
    assert aggregate is not None
    claimed = ReconciliationOutboxRecord.model_validate(
        aggregate["outbox"][next(iter(aggregate["outbox"]))]
    )
    assert claimed.state is ReconciliationOutboxDeliveryState.CLAIMED
    assert claimed.lease_until == harness.clock.now + timedelta(seconds=10)

    event_bus.block_outbox = False
    restarted = _harness(
        store=harness.store,
        event_bus=event_bus,
        clock=harness.clock,
        claimant_id="reconciliation-runtime-after-cancel",
    )
    harness.clock.advance(timedelta(seconds=9))
    assert await restarted.worker.publish_pending_once() is None
    harness.clock.advance(timedelta(seconds=1))
    assert await restarted.worker.publish_pending_once() is not None


async def test_concurrent_workers_claim_one_outbox_event() -> None:
    harness = _harness()
    await harness.worker.handle_payload(harness.event.model_dump(mode="json"))
    contender = _harness(
        store=harness.store,
        event_bus=harness.event_bus,
        clock=harness.clock,
        claimant_id="reconciliation-runtime-contender",
        group_id="reconciliation-runtime-contender-group",
    )

    results = await asyncio.wait_for(
        asyncio.gather(
            harness.worker.publish_pending_once(),
            contender.worker.publish_pending_once(),
        ),
        timeout=_WATCHDOG_SECONDS,
    )

    assert sum(result is not None for result in results) == 1
    records = tuple(
        [
            envelope
            async for envelope in harness.event_bus.subscribe(
                RECONCILIATION_OUTBOX_TOPIC,
                "reconciliation-concurrency-assertion",
            )
        ]
    )
    assert len(records) == 1


async def test_event_timeout_and_cancellation_leave_no_durable_state() -> None:
    timeout_authenticator = _BlockingAuthenticator()
    timed = _harness(
        authenticator=timeout_authenticator,
        event_handling_timeout_seconds=0.01,
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            timed.worker.handle_payload(timed.event.model_dump(mode="json")),
            timeout=_WATCHDOG_SECONDS,
        )
    assert (
        await timed.store.read_state(f"ontology:reconciliation:{timed.event.reconciliation_id}")
        is None
    )

    cancellation_authenticator = _BlockingAuthenticator()
    cancelled = _harness(authenticator=cancellation_authenticator)
    handle_task = asyncio.create_task(
        cancelled.worker.handle_payload(cancelled.event.model_dump(mode="json"))
    )
    await asyncio.wait_for(
        cancellation_authenticator.entered.wait(),
        timeout=_WATCHDOG_SECONDS,
    )
    handle_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(handle_task, timeout=_WATCHDOG_SECONDS)
    assert (
        await cancelled.store.read_state(
            f"ontology:reconciliation:{cancelled.event.reconciliation_id}"
        )
        is None
    )
