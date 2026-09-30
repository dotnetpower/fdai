from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.core.readiness import DetectionReadinessDimension
from fdai.shared.providers.cost_governance import CostAnalysisSample, CostAnomalyAdvisory
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2028, 1, 2, tzinfo=UTC)
RELEASE = "sha256:" + "4" * 64


class Advisory:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> CostAnomalyAdvisory:
        self.calls += 1
        return CostAnomalyAdvisory(
            scope_id=sample.scope_id,
            resource_id=sample.resource_id,
            amount_usd=sample.amount_usd,
            baseline_usd=Decimal("100"),
            ratio=sample.amount_usd / Decimal("100"),
            impact=Decimal("1"),
            recommendation="scale_down",
            correlation_id=sample.correlation_id,
            observed_at=sample.observed_at,
        )

    def estimate_cost_effect(self, action_type: str):
        return None


def _huginn_event(key: str) -> dict[str, object]:
    return {
        "event_id": f"event:{key}",
        "idempotency_key": key,
        "correlation_id": f"correlation:{key}",
        "source": "unit-test",
        "event_type": "availability.probe_failed",
        "occurred_at": NOW.isoformat(),
        "resource_ref": f"resource:{key}",
        "payload": {"severity": "high"},
    }


async def test_huginn_completed_dedup_fence_survives_shard_eviction() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())

    def clock() -> datetime:
        return NOW + timedelta(seconds=1)

    huginn = Huginn(bus=bus, state_store=store, dedup_capacity=1, clock=clock)

    assert await huginn.ingest(_huginn_event("a")) is not None
    assert await huginn.ingest(_huginn_event("b")) is not None
    assert (
        await Huginn(bus=bus, state_store=store, dedup_capacity=1, clock=clock).ingest(
            _huginn_event("a")
        )
        is None
    )

    assert [message.payload["idempotency_key"] for message in bus.messages_on("object.event")] == [
        "a",
        "b",
    ]


def _heimdall_event(key: str, observed_at: datetime) -> dict[str, object]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": "incident:resource-a",
        "idempotency_key": key,
        "event_id": key,
        "event_type": "availability.probe_failed",
        "occurred_at": observed_at.isoformat(),
        "resource_id": "resource-a",
        "resource_type": "service",
        "severity": "high",
    }


async def test_heimdall_rehydrates_windows_and_suppresses_redelivery() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    first = Heimdall(bus=bus, state_store=store, rate_threshold=2)
    await first.on_typed_message("object.event", _heimdall_event("e1", NOW))

    restarted = Heimdall(bus=bus, state_store=store, rate_threshold=2)
    assert await restarted.rehydrate() == 1
    await restarted.on_typed_message(
        "object.event", _heimdall_event("e2", NOW + timedelta(seconds=1))
    )
    await Heimdall(bus=bus, state_store=store, rate_threshold=2).rehydrate()
    replay = Heimdall(bus=bus, state_store=store, rate_threshold=2)
    await replay.rehydrate()
    await replay.on_typed_message("object.event", _heimdall_event("e2", NOW + timedelta(seconds=1)))

    assert len(bus.messages_on("object.anomaly")) == 1
    assert replay.behavior_snapshot()["publication:duplicate"] == 1


async def test_heimdall_alert_budget_and_security_window_survive_restart() -> None:
    store = InMemoryStateStore()
    cards: list[dict[str, object]] = []

    async def alerter(payload: dict[str, object]) -> None:
        cards.append(payload)

    first = Heimdall(
        state_store=store,
        security_high_threshold=2,
        alert_rate_per_hour=1,
        alerter_hook=alerter,
    )
    security = {
        "producer_principal": "Forseti",
        "correlation_id": "security:1",
        "idempotency_key": "security:1",
        "initiator_principal": "operator@example.com",
        "attempted_action": "ops.restart-service",
        "severity_hint": "medium",
    }
    await first.on_typed_message("object.security-event", dict(security))

    restarted = Heimdall(
        state_store=store,
        security_high_threshold=2,
        alert_rate_per_hour=1,
        alerter_hook=alerter,
    )
    await restarted.rehydrate()
    second = dict(security)
    second["correlation_id"] = "security:2"
    second["idempotency_key"] = "security:2"
    await restarted.on_typed_message("object.security-event", second)
    third = dict(security)
    third["correlation_id"] = "security:3"
    third["idempotency_key"] = "security:3"
    await restarted.on_typed_message("object.security-event", third)

    assert len(cards) == 1
    assert cards[0]["severity"] == "high"


def _readiness_event(
    pass_id: str, dimension: DetectionReadinessDimension, observed: datetime
) -> dict[str, object]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": f"readiness:{pass_id}",
        "idempotency_key": f"readiness:{pass_id}:{dimension.value}",
        "event_type": "detection.readiness.observed",
        "resource_id": "cluster-a",
        "attributes": {
            "pass_id": pass_id,
            "dimension": dimension.value,
            "status": "passed",
            "observed_at": observed.isoformat(),
            "expires_at": (observed + timedelta(hours=1)).isoformat(),
            "source": "unit-test",
            "evidence_digest": "a" * 64,
        },
    }


async def test_heimdall_readiness_pending_and_stale_pass_guard_survive_restart() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    dims = tuple(DetectionReadinessDimension)
    first = Heimdall(bus=bus, state_store=store)
    for dim in dims[:-1]:
        await first.on_typed_message("object.event", _readiness_event("pass-1", dim, NOW))

    restarted = Heimdall(bus=bus, state_store=store)
    await restarted.rehydrate()
    await restarted.on_typed_message("object.event", _readiness_event("pass-1", dims[-1], NOW))
    for dim in dims:
        await restarted.on_typed_message(
            "object.event",
            _readiness_event("pass-0", dim, NOW - timedelta(minutes=5)),
        )

    assert len(bus.messages_on("object.drift")) == 1
    assert restarted.behavior_snapshot()["detection_readiness:stale_pass"] == 1


def _cost_event(key: str, observed_at: datetime, amount: float = 200.0) -> dict[str, object]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": key,
        "idempotency_key": key,
        "event_type": "specialist.cost_sample",
        "occurred_at": observed_at.isoformat(),
        "resource_id": "resource-a",
        "attributes": {
            "scope": "scope-a",
            "resource_id": "resource-a",
            "amount_usd": amount,
            "source_authority": "unit-test-cost",
            "activation_revision": 1,
            "completeness": 1.0,
            "ontology_release_digest": RELEASE,
        },
    }


async def test_njord_fences_duplicate_and_stale_samples_across_restart() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    advisory = Advisory()
    njord = Njord(
        bus=bus,
        advisory_provider=advisory,
        package_enabled=True,
        allow_unbound_activation_reader=True,
        state_store=store,
    )
    await njord.on_typed_message("object.event", _cost_event("cost:new", NOW))

    restarted = Njord(
        bus=bus,
        advisory_provider=advisory,
        package_enabled=True,
        allow_unbound_activation_reader=True,
        state_store=store,
    )
    await restarted.rehydrate()
    await restarted.on_typed_message("object.event", _cost_event("cost:new", NOW))
    await restarted.on_typed_message(
        "object.event", _cost_event("cost:old", NOW - timedelta(minutes=1))
    )

    assert advisory.calls == 1
    assert restarted.behavior_snapshot()["cost_sample:duplicate"] == 1
    assert restarted.behavior_snapshot()["cost_sample:stale"] == 1
    answer = await restarted.introspect("scope-a", {"locale": "en"})
    assert answer.facts["sample_count"] == 1


async def test_freyr_rehydrates_forecast_state_and_rejects_duplicate_or_stale_samples() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    freyr = Freyr(bus=bus, state_store=store)
    await freyr.ingest_utilization(
        resource_id="resource-a",
        utilization=0.8,
        correlation_id="capacity:1",
        observed_at=NOW.isoformat(),
        sample_key="capacity:1",
    )
    restarted = Freyr(bus=bus, state_store=store)
    await restarted.rehydrate()
    await restarted.ingest_utilization(
        resource_id="resource-a",
        utilization=0.2,
        correlation_id="capacity:1",
        observed_at=NOW.isoformat(),
        sample_key="capacity:1",
    )
    await restarted.ingest_utilization(
        resource_id="resource-a",
        utilization=0.1,
        correlation_id="capacity:old",
        observed_at=(NOW - timedelta(minutes=1)).isoformat(),
        sample_key="capacity:old",
    )
    await restarted.ingest_utilization(
        resource_id="resource-a",
        utilization=0.6,
        correlation_id="capacity:2",
        observed_at=(NOW + timedelta(minutes=1)).isoformat(),
        sample_key="capacity:2",
    )

    assert restarted.behavior_snapshot()["capacity_sample:duplicate"] == 1
    assert restarted.behavior_snapshot()["capacity_sample:stale"] == 1
    assert restarted.sizing_advice("resource-a").forecast_util == 0.74


async def test_freyr_rehydrates_cost_evidence_for_graduation() -> None:
    store = InMemoryStateStore()
    first = Freyr(state_store=store)
    await first.on_typed_message(
        "object.cost-anomaly",
        {
            "producer_principal": "Njord",
            "correlation_id": "cost:resource-a",
            "idempotency_key": "cost-anomaly:resource-a",
            "resource_id": "resource-a",
            "id": "cost-anomaly:1",
            "observed_at": NOW.isoformat(),
        },
    )
    restarted = Freyr(state_store=store)
    await restarted.rehydrate()

    assert restarted.conversation_evidence_available({}) is False
    assert restarted._cost_evidence["resource-a"][0] == "cost-anomaly:1"


async def test_loki_suppresses_replayed_chaos_publication_and_restores_holds() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    first = Loki(bus=bus, state_store=store)
    await first.propose_experiment(
        experiment_id="experiment-a",
        action_type="ops.restart-service",
        targets=("target-a",),
        correlation_id="chaos:a",
        causal_hypothesis_ref="hypothesis:a",
        refutation_query_ref="query:a",
        impact_envelope_id="impact:a",
        recovery_plan_id="recovery:a",
        dry_run_receipt="dry-run:a",
    )
    held = await first.propose_experiment(
        experiment_id="experiment-held",
        action_type="ops.restart-service",
        targets=("target-b",),
        correlation_id="chaos:held",
    )

    restarted = Loki(bus=bus, state_store=store)
    await restarted.rehydrate()
    await restarted.propose_experiment(
        experiment_id="experiment-a",
        action_type="ops.restart-service",
        targets=("target-a",),
        correlation_id="chaos:a",
        causal_hypothesis_ref="hypothesis:a",
        refutation_query_ref="query:a",
        impact_envelope_id="impact:a",
        recovery_plan_id="recovery:a",
        dry_run_receipt="dry-run:a",
    )

    assert held.reason == "incomplete_evidence"
    assert len(restarted._held_proposals) == 1
    assert len(bus.messages_on("object.chaos-experiment")) == 1


async def test_loki_resilience_score_rehydrates_and_rejects_stale_overwrite() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    first = Loki(bus=bus, state_store=store)
    event = {
        "producer_principal": "Huginn",
        "correlation_id": "resilience:a",
        "idempotency_key": "resilience:new",
        "event_type": "specialist.resilience_score",
        "occurred_at": NOW.isoformat(),
        "resource_id": "resource-a",
        "attributes": {
            "score": 0.8,
            "action_type": "ops.restart-service",
            "effects": [
                {
                    "objective_id": "objective.availability",
                    "utility": 0.8,
                    "confidence": 0.9,
                    "metric": "availability",
                    "expected_min": 0.7,
                    "expected_max": 0.9,
                    "observation_window_seconds": 300,
                }
            ],
            "evidence_refs": ["resilience:new"],
        },
    }
    await first.on_typed_message("object.event", event)
    restarted = Loki(bus=bus, state_store=store)
    await restarted.rehydrate()
    stale = dict(event)
    stale["correlation_id"] = "resilience:old"
    stale["idempotency_key"] = "resilience:old"
    stale["occurred_at"] = (NOW - timedelta(minutes=1)).isoformat()
    stale["attributes"] = {**event["attributes"], "score": 0.1}  # type: ignore[index]
    await restarted.on_typed_message("object.event", stale)

    assert restarted._resilience_scores["resource-a"][0] == 0.8
    assert restarted.behavior_snapshot()["resilience_score:stale"] == 1
