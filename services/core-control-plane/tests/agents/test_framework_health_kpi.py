"""Round 8 H1 generic KPI, health, degradation, and logging regressions."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import pytest
from fdai.agents._framework.base import _MAX_BEHAVIOR_KEYS
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.kpi import DECLARED_AGENT_KPIS, KpiCollector, KpiEvidenceState
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.runtime_health import evaluate_degradation, safe_agent_health
from fdai.agents.thor import Thor
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


def test_heimdall_declares_t2_proposer_recovery_and_exhaustion_kpis() -> None:
    assert "t2_proposer_recovery_detection_rate" in DECLARED_AGENT_KPIS["Heimdall"]
    assert "proposer_exhaustion_to_hil_delay_seconds" in DECLARED_AGENT_KPIS["Heimdall"]


def test_report_declared_marks_stale_when_current_health_no_longer_observes_sample() -> None:
    collector = KpiCollector()
    measured = collector.record(agent="Forseti", metric="verdict_accuracy", value=0.99)

    collector.report_declared(agent="Forseti")

    latest = collector.latest(agent="Forseti", metric="verdict_accuracy")
    assert latest is not None
    assert latest.value is None
    assert latest.evidence_state is KpiEvidenceState.STALE
    assert latest.tags["previous_observed_at"] == measured.observed_at
    assert latest.observed_at


def test_kpi_coverage_counts_only_measured_values_as_reported() -> None:
    collector = KpiCollector()

    collector.report_declared(agent="Heimdall")
    coverage = collector.coverage()["Heimdall"]

    assert coverage["declared"] == len(DECLARED_AGENT_KPIS["Heimdall"])
    assert coverage["current"] == coverage["declared"]
    assert coverage["reported"] == 0
    assert coverage["measured"] == 0
    assert coverage["unavailable"] == coverage["declared"]


def test_kpi_rejects_invalid_ratio_and_missing_latency_metadata() -> None:
    collector = KpiCollector()

    with pytest.raises(ValueError, match="range"):
        collector.record(
            agent="Thor",
            metric="execution_success_rate",
            value=2.0,
            tags={"denominator": "1"},
        )
    with pytest.raises(ValueError, match="denominator"):
        collector.record(agent="Thor", metric="execution_success_rate", value=0.5)
    with pytest.raises(ValueError, match="unit=seconds"):
        collector.record(agent="Thor", metric="execution_latency_p99_seconds", value=3.0)


def test_degradation_facts_expose_workflow7_safe_effect_guarantees() -> None:
    decision = evaluate_degradation({"Forseti", "Var", "Odin", "Bragi"})
    facts = decision.to_mapping()["facts"]

    assert facts["Forseti"]["no_verdict_fallback"] is True
    assert facts["Forseti"]["operator_alert"]["required"] is True
    assert facts["Forseti"]["operator_alert"]["evidence_state"] == "not_observed"
    assert facts["Var"]["queue_preserved"]["evidence_state"] == "not_observed"
    assert facts["Var"]["timeouts_auto_extended"]["evidence_state"] == "not_observed"
    assert facts["Var"]["admin_alert"]["required"] is True
    assert facts["Var"]["allowed_action_classes"] == ["A1", "A2"]
    assert facts["Odin"]["terminal_hil_closure"]["evidence_state"] == "not_observed"
    assert facts["Odin"]["no_action_authority"] is True
    assert facts["Bragi"]["console_read_only_available"]["evidence_state"] == "not_observed"
    assert facts["Bragi"]["direct_audit_query_available"]["evidence_state"] == "not_observed"
    assert all(item["portfolio_reportable"] is True for item in facts.values())


def test_health_probe_and_log_use_structured_error_without_raw_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingAgent(Thor):
        def health(self) -> dict[str, object]:
            raise RuntimeError("secret-payload-token-123")

    caplog.set_level(logging.WARNING)

    snapshot = safe_agent_health("Thor", FailingAgent())

    assert snapshot == {
        "agent": "Thor",
        "status": "error",
        "error_type": "RuntimeError",
        "failure_code": "health_probe_failed",
    }
    assert "secret-payload-token-123" not in caplog.text
    assert all("secret-payload-token-123" not in str(record.__dict__) for record in caplog.records)


async def test_heartbeat_logs_bounded_summary_without_full_health_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="fdai.events")
    sentinel = "secret-heartbeat-token-456"

    monkeypatch.setattr(
        runtime,
        "health",
        lambda: {
            "agents": 15,
            "status": "degraded",
            "effective_enforce": False,
            "degradation": {
                "unavailable_agents": ["Forseti"],
                "effective_mode": "shadow",
                "blocks_mutation": True,
            },
            "metrics": {"publish_errors": 1},
            "agent_health": {"Forseti": {"error": sentinel}},
        },
    )
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(runtime._heartbeat(0.001))  # noqa: SLF001 - log seam
    await asyncio.sleep(0.01)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    heartbeat_records = [record for record in caplog.records if record.msg == "pantheon_heartbeat"]
    assert heartbeat_records
    assert all(sentinel not in str(record.__dict__) for record in heartbeat_records)
    assert all("agent_health" not in record.__dict__ for record in heartbeat_records)
    assert heartbeat_records[-1].bridge_failure_counters == ["publish_errors"]


def test_bridge_degrades_on_delivery_failure_counters() -> None:
    bridge = EventBusBridge(provider=InMemoryEventBus(), registry=load_pantheon())

    bridge.metrics.publish_errors = 1
    snapshot = bridge.snapshot()

    assert snapshot["status"] == "degraded"
    assert snapshot["health_failures"] == ["publish_errors"]
    assert snapshot["health_window"] == {"scope": "process", "threshold": 1}


def test_bridge_treats_stopped_consumers_as_idle_without_intentional_stop() -> None:
    bridge = EventBusBridge(provider=InMemoryEventBus(), registry=load_pantheon())

    bridge._consumer_states["Saga:object.verdict"] = "stopped"  # noqa: SLF001 - health seam
    snapshot = bridge.snapshot()

    assert snapshot["status"] == "healthy"
    assert snapshot["unavailable_agents"] == []
    assert snapshot["degraded_consumer_states"] == {}


def test_runtime_degradation_uses_bridge_snapshot_unavailable_agents() -> None:
    runtime = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="fdai.events")

    runtime.bridge._consumer_states["Saga:object.verdict"] = "gave_up"  # noqa: SLF001
    health = runtime.health()

    assert "Saga" in health["degradation"]["unavailable_agents"]
    assert "bridge_snapshot" in health["degradation"]["unavailable_sources"]["Saga"]
    assert health["effective_enforce"] is False


def test_behavior_counter_distinct_key_count_never_exceeds_cap() -> None:
    thor = Thor()

    for index in range(_MAX_BEHAVIOR_KEYS + 1):
        thor.record_behavior(f"probe:key:{index}")

    behavior = thor.behavior_snapshot()
    assert len(behavior) <= _MAX_BEHAVIOR_KEYS
    assert behavior["behavior:overflow"] >= 1
