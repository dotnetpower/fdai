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

    full = Loki(blast_radius_cap=1)
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
