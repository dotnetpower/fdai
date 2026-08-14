"""Focused tests for ordinary execution-to-observation request production."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.reconciliation_binding import (
    RECONCILIATION_REQUEST_TOPIC,
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_producer import (
    ExecutedActionObservation,
    ReconciliationRequestProductionStatus,
)
from fdai.core.ontology_platform.reconciliation_request_outbox import (
    StateStoreReconciliationRequestOutbox,
)
from fdai.delivery.reconciliation_request import (
    EffectReconciliationRequestProducer,
)
from fdai.delivery.reconciliation_request_publication import (
    EffectReconciliationRequestPublisher,
    ReconciliationRequestPublishRetryableError,
    ReconciliationRequestReceiptMismatchError,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.ontology_platform.test_reconciliation import (
    _authenticated_context,
    _fixture,
    _request,
)


def _action(artifacts: ResolvedReconciliationArtifacts) -> Action:
    target = artifacts.plan.targets[0]
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": artifacts.action_type.name,
            "action_type_ref": artifacts.plan.action_type_ref.model_dump(mode="json"),
            "target_resource_ref": target.object_id,
            "operation": artifacts.action_type.operation.value,
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
            "mode": "shadow",
            "citing_rules": ["example.rule.x"],
            "created_at": artifacts.plan.created_at,
        }
    )


class _ArtifactSource:
    def __init__(self, artifacts: ResolvedReconciliationArtifacts | None) -> None:
        self.artifacts = artifacts
        self.calls = 0

    async def resolve(self, action: Action) -> ResolvedReconciliationArtifacts | None:
        del action
        self.calls += 1
        return self.artifacts


class _ObservationSource:
    def __init__(
        self,
        observation: ExecutedActionObservation | None,
    ) -> None:
        self.observation = observation
        self.calls: list[dict[str, object]] = []

    async def observe(self, **kwargs: Any) -> ExecutedActionObservation | None:
        self.calls.append(kwargs)
        return self.observation


class _Bus:
    def __init__(self, *, fail: bool = False, receipt_topic: str | None = None) -> None:
        self.fail = fail
        self.receipt_topic = receipt_topic
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.published.append((topic, key, payload))
        return PublishReceipt(
            topic=self.receipt_topic or topic,
            partition=0,
            offset=len(self.published) - 1,
        )


class _BlockingBus(_Bus):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        self.started.set()
        await self.release.wait()
        return await super().publish(topic, key, payload)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 14, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _InFlightPublisher:
    def __init__(
        self,
        *,
        outbox: StateStoreReconciliationRequestOutbox,
        clock: _Clock,
    ) -> None:
        self.outbox = outbox
        self.clock = clock

    async def publish(self, request_id: str) -> None:
        claimed = await self.outbox.claim(
            request_id,
            claimant_id="background-publisher",
            now=self.clock(),
            lease_until=self.clock() + timedelta(seconds=10),
        )
        assert claimed is not None


def _producer(
    *,
    bus: _Bus,
    artifacts: ResolvedReconciliationArtifacts | None,
    observation_source: _ObservationSource,
    store: InMemoryStateStore | None = None,
    clock: _Clock | None = None,
) -> tuple[
    EffectReconciliationRequestProducer,
    EffectReconciliationRequestPublisher,
    StateStoreReconciliationRequestOutbox,
    _Clock,
]:
    durable_store = store or InMemoryStateStore()
    outbox = StateStoreReconciliationRequestOutbox(store=durable_store)
    runtime_clock = clock or _Clock()
    publisher = EffectReconciliationRequestPublisher(
        outbox=outbox,
        event_bus=bus,  # type: ignore[arg-type]
        claimant_id="core-test",
        clock=runtime_clock,
    )
    return (
        EffectReconciliationRequestProducer(
            outbox=outbox,
            publisher=publisher,
            artifact_source=_ArtifactSource(artifacts),
            observation_source=observation_source,
            clock=runtime_clock,
        ),
        publisher,
        outbox,
        runtime_clock,
    )


def _inputs() -> tuple[
    ResolvedReconciliationArtifacts,
    Action,
    ExecutedActionObservation,
]:
    release, target, plan, action_type = _fixture()
    artifacts = ResolvedReconciliationArtifacts(plan, action_type, release)
    action = _action(artifacts)
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        correlation_id=str(action.action_id),
    )
    observation = ExecutedActionObservation(
        evidence=request.evidence,
        observation_context=_authenticated_context(request),
        deadline=request.deadline,
        evaluated_at=request.evaluated_at,
    )
    return artifacts, action, observation


async def test_exact_v2_plan_and_independent_observation_publish_request() -> None:
    artifacts, action, observation = _inputs()
    bus = _Bus()
    observations = _ObservationSource(observation)
    producer, _, _, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=observations,
    )

    result = await producer(action, "dispatched", "receipt:executor:one")

    assert result.status is ReconciliationRequestProductionStatus.PUBLISHED
    assert result.reason_code == "broker_acknowledged"
    topic, key, payload = bus.published[0]
    assert topic == RECONCILIATION_REQUEST_TOPIC
    assert key == result.reconciliation_id
    assert payload["event_type"] == "ontology.effect_reconciliation.requested.v1"
    assert payload["plan_digest"] == artifacts.plan.digest
    assert observations.calls[0]["execution_receipt_ref"] == "receipt:executor:one"
    assert observations.calls[0]["correlation_id"] == str(action.action_id)


async def test_legacy_action_without_exact_plan_is_not_applicable() -> None:
    _, action, observation = _inputs()
    observations = _ObservationSource(observation)
    bus = _Bus()
    producer, _, _, _ = _producer(
        bus=bus,
        artifacts=None,
        observation_source=observations,
    )

    result = await producer(action, "dispatched", None)

    assert result.status is ReconciliationRequestProductionStatus.NOT_APPLICABLE
    assert result.reason_code == "semantic_v2_plan_unavailable"
    assert observations.calls == []
    assert bus.published == []


async def test_missing_independent_observation_holds_without_publish() -> None:
    artifacts, action, _ = _inputs()
    bus = _Bus()
    producer, _, _, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(None),
    )

    result = await producer(action, "dispatched", None)

    assert result.status is ReconciliationRequestProductionStatus.HELD
    assert result.reason_code == "independent_observation_unavailable"
    assert bus.published == []


async def test_v1_or_action_drift_is_rejected_without_observation() -> None:
    artifacts, action, observation = _inputs()
    observations = _ObservationSource(observation)
    bus = _Bus()
    legacy = replace(artifacts, plan=artifacts.plan.model_copy(update={"schema_version": "1.0.0"}))
    producer, _, _, _ = _producer(
        bus=bus,
        artifacts=legacy,
        observation_source=observations,
    )
    with pytest.raises(ValueError, match="existing semantic V2 plan"):
        await producer(action, "dispatched", None)

    drifted = action.model_copy(update={"params": {"replicas": 99}})
    producer, _, _, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=observations,
    )
    with pytest.raises(ValueError, match="does not match the executed Action"):
        await producer(drifted, "dispatched", None)

    for field, value in (
        ("action_type", "ops.another-action"),
        ("operation", "restart"),
    ):
        drifted = action.model_copy(update={field: value})
        with pytest.raises(ValueError, match="does not match the executed Action"):
            await producer(drifted, "dispatched", None)

    assert observations.calls == []
    assert bus.published == []


async def test_broker_failure_propagates_for_supervised_retry() -> None:
    artifacts, action, observation = _inputs()
    bus = _Bus(fail=True)
    store = InMemoryStateStore()
    producer, publisher, _, clock = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(observation),
        store=store,
    )

    with pytest.raises(ReconciliationRequestPublishRetryableError) as exc_info:
        await producer(action, "dispatched", "receipt:executor:one")

    assert isinstance(exc_info.value.__cause__, ConnectionError)
    pending = await store.read_state_page(
        "ontology:effect-reconciliation-request:",
        limit=10,
        field="outbox_state",
        value="pending",
    )
    assert pending[1] == 1
    bus.fail = False
    clock.now += timedelta(seconds=5)
    recovered = await publisher.publish()

    assert recovered is not None
    assert len(bus.published) == 1


async def test_no_effect_outcome_skips_artifact_and_observation_sources() -> None:
    artifacts, action, observation = _inputs()
    artifact_source = _ArtifactSource(artifacts)
    observation_source = _ObservationSource(observation)
    bus = _Bus()
    clock = _Clock()
    outbox = StateStoreReconciliationRequestOutbox(store=InMemoryStateStore())
    publisher = EffectReconciliationRequestPublisher(
        outbox=outbox,
        event_bus=bus,  # type: ignore[arg-type]
        claimant_id="core-test",
        clock=clock,
    )
    producer = EffectReconciliationRequestProducer(
        outbox=outbox,
        publisher=publisher,
        artifact_source=artifact_source,
        observation_source=observation_source,
        clock=clock,
    )

    result = await producer(action, "rejected_invariant", None)

    assert result.status is ReconciliationRequestProductionStatus.NOT_APPLICABLE
    assert result.reason_code == "execution_outcome_has_no_possible_effect"
    assert artifact_source.calls == 0
    assert observation_source.calls == []
    assert bus.published == []


async def test_in_flight_request_is_held_until_broker_acknowledgement() -> None:
    artifacts, action, observation = _inputs()
    clock = _Clock()
    outbox = StateStoreReconciliationRequestOutbox(store=InMemoryStateStore())
    producer = EffectReconciliationRequestProducer(
        outbox=outbox,
        publisher=_InFlightPublisher(outbox=outbox, clock=clock),  # type: ignore[arg-type]
        artifact_source=_ArtifactSource(artifacts),
        observation_source=_ObservationSource(observation),
        clock=clock,
    )

    result = await producer(action, "dispatched", "receipt:executor:one")

    assert result.status is ReconciliationRequestProductionStatus.HELD
    assert result.reason_code == "durably_queued"
    assert result.reconciliation_id is not None


async def test_distinct_observation_attempts_share_ordering_key_without_conflict() -> None:
    artifacts, action, first_observation = _inputs()
    bus = _Bus()
    store = InMemoryStateStore()
    clock = _Clock()
    first, _, _, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(first_observation),
        store=store,
        clock=clock,
    )
    first_result = await first(action, "dispatched", "receipt:executor:one")

    release, target, plan, action_type = _fixture()
    second_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        correlation_id=str(action.action_id),
        observed_at=first_observation.evidence.observed_at + timedelta(seconds=10),
        evaluated_at=first_observation.evaluated_at + timedelta(seconds=10),
    )
    second_observation = ExecutedActionObservation(
        evidence=second_request.evidence,
        observation_context=_authenticated_context(second_request),
        deadline=second_request.deadline,
        evaluated_at=second_request.evaluated_at,
    )
    second, _, _, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(second_observation),
        store=store,
        clock=clock,
    )
    second_result = await second(action, "already_applied", "receipt:executor:one")

    assert first_result.reconciliation_id == second_result.reconciliation_id
    assert len(bus.published) == 2
    assert bus.published[0][1] == bus.published[1][1] == first_result.reconciliation_id
    assert (
        bus.published[0][2]["observation_attempt_id"]
        != bus.published[1][2]["observation_attempt_id"]
    )


async def test_replayed_identical_observation_reuses_published_attempt() -> None:
    artifacts, action, observation = _inputs()
    bus = _Bus()
    store = InMemoryStateStore()
    producer, _, _, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(observation),
        store=store,
    )

    first = await producer(action, "dispatched", "receipt:executor:one")
    replayed = await producer(action, "already_applied", "receipt:executor:one")

    assert first.status is ReconciliationRequestProductionStatus.PUBLISHED
    assert replayed.status is ReconciliationRequestProductionStatus.PUBLISHED
    assert replayed.reason_code == "already_broker_acknowledged"
    assert replayed.reconciliation_id == first.reconciliation_id
    assert len(bus.published) == 1


async def test_receipt_topic_mismatch_releases_request_for_retry() -> None:
    artifacts, action, observation = _inputs()
    bus = _Bus(receipt_topic="wrong-topic")
    store = InMemoryStateStore()
    producer, _, _, clock = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(observation),
        store=store,
    )

    with pytest.raises(ReconciliationRequestReceiptMismatchError):
        await producer(action, "dispatched", "receipt:executor:one")

    pending, count = await store.read_state_page(
        "ontology:effect-reconciliation-request:",
        limit=10,
        field="outbox_state",
        value="pending",
    )
    assert count == 1
    assert pending[0]["available_at"] == (clock() + timedelta(seconds=5)).isoformat()
    assert pending[0]["last_error"] == "broker_receipt_topic_mismatch"


async def test_cancelled_publish_is_reclaimed_after_lease_expiry() -> None:
    artifacts, action, observation = _inputs()
    bus = _BlockingBus()
    store = InMemoryStateStore()
    clock = _Clock()
    producer, _, outbox, _ = _producer(
        bus=bus,
        artifacts=artifacts,
        observation_source=_ObservationSource(observation),
        store=store,
        clock=clock,
    )
    attempt = asyncio.create_task(producer(action, "dispatched", "receipt:executor:one"))
    await bus.started.wait()
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    claimed, count = await store.read_state_page(
        "ontology:effect-reconciliation-request:",
        limit=10,
        field="outbox_state",
        value="claimed",
    )
    assert count == 1
    request_id = str(claimed[0]["request_id"])
    clock.now += timedelta(seconds=10)
    recovery_bus = _Bus()
    recovery = EffectReconciliationRequestPublisher(
        outbox=outbox,
        event_bus=recovery_bus,  # type: ignore[arg-type]
        claimant_id="recovery-core",
        clock=clock,
    )
    recovered = await recovery.publish(request_id)

    assert recovered is not None
    assert len(recovery_bus.published) == 1
