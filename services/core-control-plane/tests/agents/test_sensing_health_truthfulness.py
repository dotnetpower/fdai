"""Round 8 package S health and KPI truthfulness regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.core.readiness import DetectionReadinessDimension
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def _clock(*values: datetime):
    items = list(values)

    def next_value() -> datetime:
        return items.pop(0) if items else values[-1]

    return next_value


def _event(key: str, *, inventory: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if inventory:
        payload["inventory_change"] = {
            "resource": {"resource_id": "resource:one", "type": "vm"},
            "change_kind": "upsert",
        }
    return {
        "idempotency_key": key,
        "event_id": f"event:{key}",
        "event_type": "generic",
        "source": "test-source",
        "resource_id": "resource:one",
        "occurred_at": NOW.isoformat(),
        "payload": payload,
    }


async def test_huginn_health_reports_checkpoint_and_null_discovery_evidence() -> None:
    process_local = Huginn()
    health = process_local.health()

    assert health["status"] == "degraded"
    assert health["checkpoint"]["durability"] == "process_local"
    assert health["discovery"]["cursor"]["value"] is None
    assert health["discovery"]["cursor"]["evidence_state"] == "not_connected"
    assert health["kpis"]["discovery_cursor_lag_seconds"]["value"] is None

    store = InMemoryStateStore()
    durable = Huginn(state_store=store, clock=lambda: NOW)
    await durable.rehydrate()
    health = durable.health()
    assert health["status"] == "ok"
    assert health["checkpoint"]["durability"] == "durable"
    assert health["checkpoint"]["retained_cursor_source"] == "state_store"
    assert health["checkpoint"]["last_checkpoint_age_seconds"]["value"] == 0.0


async def test_huginn_latency_and_dedup_accuracy_use_observed_denominators() -> None:
    store = InMemoryStateStore()
    projection_calls = 0

    async def projector(_payload: dict[str, Any]) -> None:
        nonlocal projection_calls
        projection_calls += 1

    times = [
        NOW,
        NOW + timedelta(milliseconds=10),
        NOW + timedelta(milliseconds=20),
        NOW + timedelta(milliseconds=30),
        NOW + timedelta(milliseconds=40),
        NOW + timedelta(milliseconds=50),
        NOW + timedelta(milliseconds=60),
        NOW + timedelta(milliseconds=70),
    ]
    huginn = Huginn(
        state_store=store,
        discovery_projector=projector,
        clock=_clock(*times),
    )

    assert await huginn.ingest(_event("one", inventory=True)) is not None
    assert await huginn.ingest(_event("two", inventory=True)) is not None
    restarted = Huginn(
        state_store=store,
        discovery_projector=projector,
        clock=_clock(*times),
    )
    assert await restarted.ingest(_event("two", inventory=True)) is None
    collision_probe = Huginn(
        state_store=store,
        discovery_projector=projector,
        clock=_clock(*times),
    )
    changed = _event("two", inventory=True)
    changed["resource_id"] = "resource:two"
    with pytest.raises(ValueError):
        await collision_probe.ingest(changed)

    latency_health = huginn.health()
    duplicate_health = restarted.health()
    collision_health = collision_probe.health()
    assert projection_calls == 2
    assert (
        latency_health["kpis"]["event_processing_latency_p99_seconds"]["evidence_state"]
        == "measured"
    )
    assert latency_health["kpis"]["discovery_delivery_latency_p99_seconds"]["denominator"] == 2
    assert duplicate_health["kpis"]["dedup_accuracy"]["value"] == 1.0
    assert collision_health["kpis"]["dedup_accuracy"]["value"] == 0.0


async def test_heimdall_health_and_kpis_report_real_observation_state() -> None:
    heimdall = Heimdall(forecast_clock=lambda: NOW)

    await heimdall.on_typed_message(
        "object.action-run",
        {"producer_principal": "Thor", "state": "succeeded"},
    )
    heimdall.record_anomaly_outcome("true_positive")
    heimdall.record_anomaly_outcome("false_positive")
    heimdall.record_anomaly_outcome("false_negative")
    heimdall.record_forecast_absolute_percentage_error(12.5)

    for dimension in DetectionReadinessDimension:
        await heimdall.on_typed_message(
            "object.event",
            {
                "producer_principal": "Huginn",
                "event_type": "detection.readiness.observed",
                "resource_id": "resource:one",
                "attributes": {
                    "pass_id": "pass-1",
                    "dimension": dimension.value,
                    "status": "passed",
                    "observed_at": (NOW - timedelta(seconds=30)).isoformat(),
                    "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
                    "source": "probe",
                    "evidence_digest": "1" * 64,
                },
            },
        )

    health = heimdall.health()

    assert health["status"] == "degraded"
    assert health["dependencies"]["action_observation_hook"] == "unavailable"
    assert health["backlog"]["pending_effect_observations"] == 1
    assert health["kpis"]["anomaly_precision"]["value"] == 0.5
    assert health["kpis"]["anomaly_recall"]["value"] == 0.5
    assert health["kpis"]["forecast_mape"]["value"] == 12.5
    assert health["kpis"]["discovery_coverage_detection_rate"]["value"] == 1 / 6
    assert health["kpis"]["stale_inventory_detection_delay_seconds"]["value"] == 30.0


async def test_njord_health_kpis_cost_impact_and_failure_keys_are_truthful() -> None:
    njord = Njord()

    await njord.ingest_cost_sample(scope="scope", amount_usd=1.0)
    health = njord.health()
    estimate = njord.cost_impact("ops.scale-down")

    assert health["status"] == "degraded"
    assert health["degradation"]["domain_actions"] == "hil"
    assert estimate.monthly_delta_usd is None
    assert estimate.evidence_state == "not_connected"
    assert njord.behavior_snapshot()["cost_sample:invalid_time"] == 1

    njord.record_cost_forecast_outcome(forecast_usd=100.0, actual_usd=125.0)
    njord.record_savings_realized(savings_usd=12.5)
    njord.record_budget_breach_outcome(missed=False)
    njord.record_budget_breach_outcome(missed=True)
    health = njord.health()

    assert health["kpis"]["cost_forecast_mape"]["value"] == 0.25
    assert health["kpis"]["savings_realized_usd"]["value"] == 12.5
    assert health["kpis"]["budget_breach_miss_rate"]["value"] == 0.5


async def test_freyr_degrades_skips_missing_source_time_and_measures_outcomes() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    freyr = Freyr(bus=bus, clock=lambda: NOW)

    await freyr.ingest_utilization(resource_id="resource:capacity", utilization=0.8)
    freyr.record_capacity_forecast_outcome(
        resource_id="resource:capacity",
        forecast_utilization=0.7,
        actual_utilization=0.9,
        provisioned="under",
    )
    health = freyr.health()

    assert bus.messages_on("object.capacity-forecast") == []
    assert health["status"] == "degraded"
    assert health["state"]["source_time_missing_samples"] == 1
    assert health["kpis"]["capacity_forecast_error"]["value"] == pytest.approx(0.2)
    assert health["kpis"]["under_provisioning_rate"]["value"] == 1.0
    assert health["kpis"]["over_provisioning_rate"]["value"] == 0.0


async def test_loki_degrades_with_process_local_reservations_and_reports_experiment_kpis() -> None:
    loki = Loki(blast_radius_cap=2, clock=lambda: NOW)
    evidence = {
        "causal_hypothesis_ref": "causal",
        "refutation_query_ref": "query",
        "impact_envelope_id": "impact",
        "recovery_plan_id": "recovery",
        "dry_run_receipt": "dry-run",
    }

    await loki.propose_experiment(
        experiment_id="exp-1",
        action_type="tool.run-chaos-experiment",
        targets=("target-1",),
        **evidence,
    )
    await loki.propose_experiment(
        experiment_id="exp-2",
        action_type="tool.run-chaos-experiment",
        targets=("target-2", "target-3"),
        **evidence,
    )
    for phase, score in (("baseline", 0.4), ("post", 0.7)):
        await loki.on_typed_message(
            "object.event",
            {
                "producer_principal": "Huginn",
                "correlation_id": "resilience-correlation",
                "idempotency_key": f"resilience-{phase}",
                "event_id": f"event:resilience-{phase}",
                "event_type": "specialist.resilience_score",
                "occurred_at": NOW.isoformat(),
                "ingested_at": NOW.isoformat(),
                "resource_id": "resource-1",
                "attributes": {
                    "score": score,
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
                    "evidence_refs": [f"event:resilience-{phase}"],
                    "experiment_id": "exp-1",
                    "observation_phase": phase,
                },
            },
        )

    health = loki.health()

    assert health["status"] == "degraded"
    assert health["reservation"]["durability"] == "process_local"
    assert health["degradation"]["domain_actions"] == "hil"
    assert health["kpis"]["blast_radius_adherence_rate"]["denominator"] == 2
    assert health["kpis"]["blast_radius_adherence_rate"]["value"] == 0.5
    assert health["kpis"]["resilience_improvement_delta"]["value"] == pytest.approx(0.3)
