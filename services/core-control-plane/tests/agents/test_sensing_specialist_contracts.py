from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn, HuginnIngressRejected
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.core.capacity import CapacityGraduationController
from fdai.rule_catalog.schema.capacity_graduation_policy import (
    load_capacity_graduation_policy,
)
from fdai.shared.providers.cost_governance import (
    CostAnalysisSample,
    CostAnomalyAdvisory,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2028, 1, 2, tzinfo=UTC)


class NoFindingProvider:
    async def analyze_cost_sample(
        self,
        sample: CostAnalysisSample,
    ) -> CostAnomalyAdvisory | None:
        return None

    def estimate_cost_effect(self, action_type: str) -> None:
        return None


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _controller() -> CapacityGraduationController:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    return CapacityGraduationController(
        load_capacity_graduation_policy(repo_root / "rule-catalog/capacity-graduation-policy.yaml")
    )


def _cost_sample_event(event_type: str = "specialist.cost_sample") -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": "cost:corr",
        "idempotency_key": "cost:key",
        "event_id": "event:cost",
        "event_type": event_type,
        "occurred_at": NOW.isoformat(),
        "ingested_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resource_id": "resource:cost",
        "attributes": {
            "scope": "scope:cost",
            "amount_usd": 100.0,
            "source_authority": "test-cost-source",
            "completeness": 1.0,
            "ontology_release_digest": "sha256:" + "3" * 64,
        },
    }


def _capacity_event(event_type: str = "specialist.capacity_sample") -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": "capacity:corr",
        "idempotency_key": "capacity:key",
        "event_id": "event:capacity",
        "event_type": event_type,
        "occurred_at": NOW.isoformat(),
        "ingested_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resource_id": "resource:capacity",
        "attributes": {"utilization": 0.7},
    }


def _chaos_evidence() -> dict[str, str]:
    return {
        "causal_hypothesis_ref": "causal:one",
        "refutation_query_ref": "query:one",
        "impact_envelope_id": "impact:one",
        "recovery_plan_id": "recovery:one",
        "dry_run_receipt": "dry-run:one",
    }


def _anomaly_event(
    *,
    correlation_id: str = "corr:anomaly",
    idempotency_key: str = "event:anomaly",
    resource_id: str = "resource:anomaly",
    severity: str = "high",
) -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "event_id": idempotency_key,
        "event_type": "service.error",
        "occurred_at": NOW.isoformat(),
        "ingested_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resource_id": resource_id,
        "severity": severity,
    }


async def test_huginn_change_projection_uses_trusted_ingested_at_without_source_time() -> None:
    bus = _bus()
    huginn = Huginn(bus=bus, clock=lambda: NOW)

    payload = await huginn.ingest(
        {
            "idempotency_key": "activity-no-source-time",
            "event_id": "event:activity-no-source-time",
            "correlation_id": "corr:activity",
            "event_type": "generic",
            "source": "azure-activity-log",
            "resource_id": "resource:one",
            "payload": {"signal_kind": "azure.activity_log", "actor": {"principal_id": "actor"}},
        }
    )

    assert payload is not None
    (change,) = bus.messages_on("object.change")
    assert change.payload["occurred_at"] == NOW.isoformat()
    assert payload["normalized_change"]["occurred_at"] == NOW.isoformat()


async def test_huginn_change_projection_rejects_malformed_source_time() -> None:
    huginn = Huginn(clock=lambda: NOW)

    try:
        await huginn.ingest(
            {
                "idempotency_key": "activity-bad-source-time",
                "event_id": "event:activity-bad-source-time",
                "correlation_id": "corr:activity",
                "event_type": "generic",
                "source": "azure-activity-log",
                "resource_id": "resource:one",
                "occurred_at": "not-a-time",
                "payload": {
                    "signal_kind": "azure.activity_log",
                    "actor": {"principal_id": "actor"},
                },
            }
        )
    except HuginnIngressRejected as exc:
        assert exc.reason_code == "timestamp_not_rfc3339"
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("Huginn accepted a malformed source timestamp")


async def test_njord_records_ignored_event_and_provider_no_finding() -> None:
    bus = _bus()
    njord = Njord(
        bus=bus,
        advisory_provider=NoFindingProvider(),
        package_enabled=True,
        allow_unbound_activation_reader=True,
    )

    await njord.on_typed_message("object.event", _cost_sample_event("specialist.other"))
    await njord.on_typed_message("object.event", _cost_sample_event())

    behavior = njord.behavior_snapshot()
    assert behavior["cost_sample:ignored_event"] == 1
    assert behavior["cost_sample:no_finding"] == 1
    assert bus.messages_on("object.cost-anomaly") == []


async def test_freyr_records_ignored_inputs_and_transport_unavailable() -> None:
    freyr = Freyr(clock=lambda: NOW)

    await freyr.on_typed_message("object.action-run", {})
    await freyr.on_typed_message("object.event", _capacity_event("specialist.other"))
    await freyr.on_typed_message("object.event", _capacity_event())

    behavior = freyr.behavior_snapshot()
    assert behavior["typed_message:ignored"] == 1
    assert behavior["capacity_sample:ignored_event"] == 1
    assert behavior["capacity_sample:accepted"] == 1
    assert behavior["capacity_forecast:transport_unavailable"] == 1


async def test_freyr_holds_missing_observed_at_as_freshness_gap() -> None:
    bus = _bus()
    freyr = Freyr(bus=bus, clock=lambda: NOW)

    await freyr.ingest_utilization(resource_id="resource:capacity", utilization=0.8)

    assert bus.messages_on("object.capacity-forecast") == []
    assert freyr.behavior_snapshot()["capacity_sample:source_time_missing"] == 1
    assert freyr.health()["state"]["source_time_missing_samples"] == 1


async def test_freyr_omits_stale_or_uncorrelated_cost_evidence() -> None:
    bus = _bus()
    freyr = Freyr(bus=bus, graduation_controller=_controller(), clock=lambda: NOW)
    stale_cost = {
        "producer_principal": "Njord",
        "correlation_id": "graduation:corr",
        "idempotency_key": "cost:stale",
        "resource_id": "resource:capacity",
        "evidence_ref": "evidence:cost",
        "observed_at": (NOW - timedelta(hours=2)).isoformat(),
    }
    uncorrelated_cost = {
        **stale_cost,
        "correlation_id": "graduation:other",
        "idempotency_key": "cost:uncorrelated",
        "observed_at": NOW.isoformat(),
    }
    event = {
        "producer_principal": "Huginn",
        "correlation_id": "graduation:corr",
        "idempotency_key": "capacity:graduation",
        "event_id": "event:capacity:graduation",
        "event_type": "specialist.capacity_graduation_evidence",
        "occurred_at": NOW.isoformat(),
        "ingested_at": NOW.isoformat(),
        "resource_id": "resource:capacity",
        "attributes": {
            "transition": "dedicated_vector_store",
            "target_ref": "resource:capacity",
            "source_authority_ref": "measurement:capacity",
            "evidence_refs": ["evidence:capacity"],
            "complete": True,
            "synthetic": False,
            "projected_cost_ratio": 1.0,
            "capacity_ratio": 0.8,
        },
    }

    await freyr.on_typed_message("object.cost-anomaly", stale_cost)
    await freyr.on_typed_message("object.event", event)
    first = bus.messages_on("object.capacity-graduation-recommendation")[-1].payload
    assert first["reason_codes"] == ["cost_evidence_missing"]
    assert "cost_evidence_ref" not in first
    assert freyr.behavior_snapshot()["capacity_graduation:cost_evidence_stale"] == 1

    await freyr.on_typed_message("object.cost-anomaly", uncorrelated_cost)
    await freyr.on_typed_message("object.event", {**event, "idempotency_key": "capacity:two"})
    assert freyr.behavior_snapshot()["capacity_graduation:cost_evidence_uncorrelated"] == 1


async def test_loki_records_ignored_inputs_and_invalid_closures() -> None:
    loki = Loki()

    await loki.on_typed_message("object.verdict", {})
    await loki.on_typed_message(
        "object.event",
        {
            "producer_principal": "Huginn",
            "correlation_id": "other:corr",
            "idempotency_key": "other:key",
            "event_type": "specialist.other",
        },
    )
    await loki.on_typed_message(
        "object.action-run",
        {"producer_principal": "Forseti", "state": "rolled_back", "params": {}},
    )
    await loki.on_typed_message(
        "object.action-run",
        {"producer_principal": "Thor", "state": "running", "params": {}},
    )
    await loki.on_typed_message(
        "object.action-run",
        {"producer_principal": "Thor", "state": "rolled_back", "params": []},
    )
    await loki.on_typed_message(
        "object.action-run",
        {
            "producer_principal": "Thor",
            "state": "rolled_back",
            "action_type": "tool.run-chaos-experiment",
            "params": {"experiment_id": "unknown", "targets": ["target:one"]},
        },
    )

    behavior = loki.behavior_snapshot()
    assert behavior["typed_message:ignored"] == 1
    assert behavior["chaos_schedule:ignored_event"] == 1
    assert behavior["chaos_reservation:invalid_closure_producer"] == 1
    assert behavior["chaos_reservation:ignored_nonterminal_closure"] == 1
    assert behavior["chaos_reservation:malformed_closure"] == 1
    assert behavior["chaos_reservation:missing_closure"] == 1


async def test_loki_records_blast_radius_hold_and_publication_unavailable_cleanup() -> None:
    bus = _bus()
    loki = Loki(bus=bus, blast_radius_cap=2)
    loki._proposal_limiter = RateLimiter(per_minute=1, per_hour=100, now=lambda: 0.0)

    first = await loki.propose_experiment(
        experiment_id="experiment:one",
        action_type="tool.run-chaos-experiment",
        targets=("target:one",),
        **_chaos_evidence(),
    )
    second = await loki.propose_experiment(
        experiment_id="experiment:two",
        action_type="tool.run-chaos-experiment",
        targets=("target:two",),
        **_chaos_evidence(),
    )

    assert first.accepted
    assert not second.accepted
    assert second.reason == "publication_unavailable"
    assert "target:two" not in loki._in_flight_targets
    assert loki.behavior_snapshot()["chaos_proposal:publication_unavailable"] == 1

    full = Loki(bus=_bus(), blast_radius_cap=1)
    await full.propose_experiment(
        experiment_id="experiment:three",
        action_type="tool.run-chaos-experiment",
        targets=("target:three",),
        **_chaos_evidence(),
    )
    held = await full.propose_experiment(
        experiment_id="experiment:four",
        action_type="tool.run-chaos-experiment",
        targets=("target:four",),
        **_chaos_evidence(),
    )
    assert held.reason == "blast_radius_full"
    assert full.behavior_snapshot()["chaos_proposal:blast_radius_full"] == 1


async def test_heimdall_records_unknown_topic_missing_resource_and_collecting_window() -> None:
    heimdall = Heimdall(rate_threshold=2)

    await heimdall.on_typed_message("object.unknown", {})
    await heimdall.on_typed_message("object.event", _anomaly_event(resource_id=""))
    await heimdall.on_typed_message("object.event", _anomaly_event())

    behavior = heimdall.behavior_snapshot()
    assert behavior["typed_message:ignored"] == 1
    assert behavior["anomaly_event:missing_resource"] == 1
    assert behavior["anomaly_window:collecting"] == 1


async def test_heimdall_refuses_uncorrelated_anomaly_before_publish() -> None:
    bus = _bus()
    heimdall = Heimdall(bus=bus, rate_threshold=1)

    await heimdall.on_typed_message("object.event", _anomaly_event(correlation_id=""))

    assert bus.messages_on("object.anomaly") == []
    assert heimdall.behavior_snapshot()["incident_candidate_missing_correlation"] == 1


async def test_heimdall_records_duplicate_severity_suppression() -> None:
    bus = _bus()
    accepted: list[dict[str, Any]] = []

    async def hook(payload: dict[str, Any]) -> bool:
        accepted.append(payload)
        return True

    heimdall = Heimdall(bus=bus, rate_threshold=1, incident_candidate_hook=hook)
    event = _anomaly_event()

    await heimdall.on_typed_message("object.event", event)
    await heimdall.on_typed_message("object.event", dict(event))

    assert len(accepted) == 1
    assert len(bus.messages_on("object.anomaly")) == 1
    assert heimdall.behavior_snapshot()["anomaly_episode:suppressed_duplicate_severity"] == 1


async def test_specialist_event_builders_parsers_and_cost_publisher_round_trip() -> None:
    from decimal import Decimal

    import pytest
    from fdai.agents._framework.specialist_ingress import (
        build_capacity_sample_event,
        build_chaos_schedule_event,
        has_resource_id_conflict,
        parse_capacity_sample,
        parse_chaos_schedule,
        parse_cost_sample,
        parse_resilience_score,
    )
    from fdai.delivery.cost_sample_publisher import EventBusCostSamplePublisher
    from fdai.shared.providers.cost_governance import CostObservation
    from fdai.shared.providers.testing.event_bus import InMemoryEventBus

    cap_event = build_capacity_sample_event(
        resource_id="resource:vm-1",
        utilization=0.65,
        observed_at=NOW.isoformat(),
        correlation_id="corr:cap",
        idempotency_key="key:cap-1",
    )
    parsed_cap = parse_capacity_sample(cap_event)
    assert parsed_cap is not None
    assert parsed_cap.resource_id == "resource:vm-1"
    assert parsed_cap.utilization == 0.65

    chaos_event = build_chaos_schedule_event(
        experiment_id="exp:1",
        action_type="tool.run-chaos-experiment",
        targets=("target:1", "target:2"),
        correlation_id="corr:chaos",
        idempotency_key="key:chaos-1",
        occurred_at=NOW.isoformat(),
    )
    parsed_chaos = parse_chaos_schedule(chaos_event)
    assert parsed_chaos is not None
    assert parsed_chaos.targets == ("target:1", "target:2")

    dup_chaos = {
        **chaos_event,
        "attributes": {**chaos_event["attributes"], "targets": ["target:1", "target:1"]},
    }
    assert parse_chaos_schedule(dup_chaos) is None

    res_signal = parse_resilience_score(
        {
            "event_type": "specialist.resilience_score",
            "resource_id": "resource:vm-1",
            "correlation_id": "corr:res",
            "occurred_at": NOW.isoformat(),
            "attributes": {"score": 0.9, "experiment_id": "exp:1"},
        }
    )
    assert res_signal is not None
    assert res_signal.score == 0.9
    assert has_resource_id_conflict({"resource_id": "ok", "attributes": {"resource_id": "bad\x00"}})

    raw_bus = InMemoryEventBus()
    publisher = EventBusCostSamplePublisher(bus=raw_bus, topic="fdai.events")
    observation = CostObservation(
        observation_id="obs:1",
        package_id="cost-governance",
        scope_id="scope:sub-1",
        service_id="Microsoft.Compute",
        source_uri="resource:vm-1",
        source_authority="azure-consumption",
        event_start_at=NOW - timedelta(hours=2),
        event_end_at=NOW - timedelta(hours=1),
        observed_at=NOW,
        recorded_at=NOW + timedelta(minutes=1),
        retention_until=NOW + timedelta(days=30),
        amount=Decimal("42.50"),
        currency="USD",
        completeness=Decimal("1.0"),
        ontology_release_id="release:1",
        ontology_release_digest="sha256:" + "3" * 64,
        evidence_digest="sha256:" + "4" * 64,
    )
    await publisher.publish_cost_sample(observation, activation_revision=1)
    published_envelope = raw_bus._records["fdai.events"][-1][1]
    parsed_cost = parse_cost_sample(published_envelope)
    assert parsed_cost is not None
    assert parsed_cost.observed_at == NOW.isoformat()

    with pytest.raises(ValueError, match="activation revision"):
        await publisher.publish_cost_sample(observation, activation_revision=True)


async def test_specialist_and_sensing_hardening_guards() -> None:
    from uuid import UUID

    import pytest
    from fdai.shared.contracts.models import ForecastOutcome

    with pytest.raises(ValueError, match="smoothing_alpha"):
        Freyr(smoothing_alpha=0.0)
    with pytest.raises(ValueError, match="scale thresholds"):
        Freyr(scale_up_threshold=0.2, scale_down_threshold=0.5)
    with pytest.raises(ValueError, match="blast_radius_cap"):
        Loki(blast_radius_cap=0)
    with pytest.raises(ValueError, match="dedup_capacity"):
        Huginn(dedup_capacity=True)

    store = InMemoryStateStore()
    await store.write_state(
        "pantheon/freyr/accepted-samples/pending-1",
        {"sample_key": "pending-key", "state": "pending"},
    )
    await store.write_state(
        "pantheon/freyr/accepted-samples/done-1",
        {"sample_key": "done-key", "state": "completed"},
    )
    freyr = Freyr(bus=_bus(), state_store=store, clock=lambda: NOW)
    await freyr.rehydrate()
    assert "pending-key" not in freyr._accepted_sample_keys
    assert "done-key" in freyr._accepted_sample_keys

    await freyr.ingest_utilization(
        resource_id="resource:vm-1",
        utilization=0.5,
        observed_at=NOW.isoformat(),
        sample_key="fresh-key",
    )
    assert freyr.behavior_snapshot()["capacity_forecast:published"] == 1

    njord = Njord()
    with pytest.raises(ValueError, match="cost forecast"):
        njord.record_cost_forecast_outcome(forecast_usd=True, actual_usd=10.0)
    with pytest.raises(ValueError, match="savings_usd"):
        njord.record_savings_realized(savings_usd=-1.0)
    with pytest.raises(ValueError, match="missed"):
        njord.record_budget_breach_outcome(missed=1)  # type: ignore[arg-type]

    loki = Loki()
    assert await loki.run_adversarial_generation(design_ref="   ") == 0
    assert loki.behavior_snapshot()["adversarial_scenario:invalid_design_ref"] == 1

    heimdall = Heimdall()
    outcome = ForecastOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=1),
            "idempotency_key": "forecast-outcome-1",
            "correlation_id": "corr-1",
            "prediction_id": UUID(int=100),
            "detector_id": "capacity-linear",
            "detector_version": "1.0.0",
            "access_scope_digest": "a" * 64,
            "target_digest": "b" * 64,
            "metric": "capacity_percent",
            "feature_cutoff": NOW,
            "horizon_started_at": NOW,
            "horizon_ended_at": NOW + timedelta(hours=1),
            "direction": "rising",
            "threshold": 90.0,
            "predicted_value": 95.0,
            "interval_lower": 91.0,
            "interval_upper": 99.0,
            "observed_value": 70.0,
            "actual_breach_at": None,
            "label": "false_positive",
            "evidence_refs": ["metric-window:1"],
            "telemetry_completeness": "complete",
            "closed_at": NOW + timedelta(hours=2),
            "mode": "shadow",
        }
    )
    assert await heimdall.publish_forecast_outcome(outcome) is False
    assert heimdall.behavior_snapshot()["forecast_publication:transport_unavailable"] == 1


async def test_heimdall_records_chaos_and_t2_publication_noops() -> None:
    heimdall = Heimdall()

    await heimdall.on_typed_message(
        "object.chaos-experiment",
        {
            "producer_principal": "Loki",
            "correlation_id": "chaos:corr",
            "idempotency_key": "chaos:key",
            "experiment_id": "experiment:one",
            "action_type": "tool.run-chaos-experiment",
            "targets": ["target:one"],
            **_chaos_evidence(),
        },
    )
    await heimdall.on_typed_message(
        "object.event",
        {
            "producer_principal": "Huginn",
            "correlation_id": "t2:corr",
            "idempotency_key": "t2:key",
            "event_id": "event:t2",
            "event_type": "control_plane.t2_proposer_attempt",
            "resource_id": "control-plane:t2-proposer",
            "attributes": {
                "terminal": True,
                "status": "failed",
                "preferred_route_ref": "primary",
                "failure_class": "provider_error",
            },
        },
    )

    behavior = heimdall.behavior_snapshot()
    assert behavior["chaos_experiment:grounded"] == 1
    assert behavior["chaos_experiment:publication_unavailable"] == 1
    assert behavior["t2_proposer:unavailable"] == 1
    assert behavior["incident_candidate_hook:unavailable"] == 1


async def test_loki_without_bus_or_outbox_does_not_accept_a_chaos_proposal() -> None:
    loki = Loki(blast_radius_cap=2)

    proposal = await loki.propose_experiment(
        experiment_id="experiment:unpublished",
        action_type="tool.run-chaos-experiment",
        targets=("target:unpublished",),
        **_chaos_evidence(),
    )

    assert not proposal.accepted
    assert proposal.reason == "publication_unavailable"
    assert "target:unpublished" not in loki._in_flight_targets  # noqa: SLF001
    assert loki.behavior_snapshot()["chaos_proposal:publication_unavailable"] == 1


async def test_loki_durable_no_bus_keeps_pending_outbox_without_accepting() -> None:
    store = InMemoryStateStore()
    loki = Loki(state_store=store, blast_radius_cap=2)

    proposal = await loki.propose_experiment(
        experiment_id="experiment:durable-unpublished",
        action_type="tool.run-chaos-experiment",
        targets=("target:durable-unpublished",),
        **_chaos_evidence(),
    )

    assert not proposal.accepted
    assert proposal.reason == "publication_unavailable"
    assert "target:durable-unpublished" not in loki._in_flight_targets  # noqa: SLF001

    restarted_bus = _bus()
    restarted = Loki(bus=restarted_bus, state_store=store, blast_radius_cap=2)
    replayed = await restarted.propose_experiment(
        experiment_id="experiment:durable-unpublished",
        action_type="tool.run-chaos-experiment",
        targets=("target:durable-unpublished",),
        **_chaos_evidence(),
    )

    assert replayed.accepted
    assert len(restarted_bus.messages_on("object.chaos-experiment")) == 1
