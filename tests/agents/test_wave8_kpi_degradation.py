"""Wave 8 tests: KPI collectors + degradation drills + promotion gates."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.kpi import KpiCollector, PromotionGate, PromotionGateThreshold
from fdai.agents._framework.registry import PantheonRegistryError, load_pantheon
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRunState, Thor

# ---------------------------------------------------------------------------
# KPI collector
# ---------------------------------------------------------------------------


def test_kpi_collector_records_and_returns_latest() -> None:
    c = KpiCollector()
    c.record(agent="Forseti", metric="verdict_accuracy", value=0.90)
    c.record(agent="Forseti", metric="verdict_accuracy", value=0.95)
    latest = c.latest(agent="Forseti", metric="verdict_accuracy")
    assert latest is not None
    assert latest.value == 0.95


def test_kpi_collector_all_for_returns_agent_samples() -> None:
    c = KpiCollector()
    c.record(agent="Thor", metric="execution_success_rate", value=0.99)
    c.record(agent="Bragi", metric="routing_accuracy", value=0.92)
    thor_samples = c.all_for("Thor")
    assert len(thor_samples) == 1
    assert thor_samples[0].metric == "execution_success_rate"


def test_kpi_collector_ring_is_bounded_and_latest_survives_eviction() -> None:
    # An agent records KPIs for the whole process lifetime; the sample ring
    # must be bounded, and latest() must still return the true most-recent
    # value even after that sample has been evicted from the ring.
    from fdai.agents._framework.kpi import _MAX_SAMPLES

    c = KpiCollector()
    for i in range(_MAX_SAMPLES + 100):
        c.record(agent="Forseti", metric="verdict_accuracy", value=float(i))
    assert len(c.samples) == _MAX_SAMPLES
    latest = c.latest(agent="Forseti", metric="verdict_accuracy")
    assert latest is not None
    # The very first sample is long evicted, but latest is still correct.
    assert latest.value == float(_MAX_SAMPLES + 100 - 1)


# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------


def test_promotion_gate_passes_when_all_thresholds_met() -> None:
    c = KpiCollector()
    c.record(agent="Forseti", metric="verdict_accuracy", value=0.97)
    c.record(agent="Forseti", metric="t2_escalation_rate", value=0.05)
    gate = PromotionGate(
        workflow_id="security-escalation",
        thresholds=(
            PromotionGateThreshold(metric="Forseti.verdict_accuracy", min=0.95),
            PromotionGateThreshold(metric="Forseti.t2_escalation_rate", max=0.10),
        ),
    )
    passed, outcomes = gate.evaluate(c)
    assert passed is True
    assert outcomes["Forseti.verdict_accuracy"] is True


def test_promotion_gate_fails_when_min_not_met() -> None:
    c = KpiCollector()
    c.record(agent="Forseti", metric="verdict_accuracy", value=0.80)
    gate = PromotionGate(
        workflow_id="wf",
        thresholds=(PromotionGateThreshold(metric="Forseti.verdict_accuracy", min=0.95),),
    )
    passed, _ = gate.evaluate(c)
    assert passed is False


def test_promotion_gate_fails_when_max_exceeded() -> None:
    c = KpiCollector()
    c.record(agent="Forseti", metric="t2_escalation_rate", value=0.20)
    gate = PromotionGate(
        workflow_id="wf",
        thresholds=(PromotionGateThreshold(metric="Forseti.t2_escalation_rate", max=0.10),),
    )
    passed, _ = gate.evaluate(c)
    assert passed is False


def test_promotion_gate_fails_when_metric_missing() -> None:
    c = KpiCollector()  # no samples
    gate = PromotionGate(
        workflow_id="wf",
        thresholds=(PromotionGateThreshold(metric="Forseti.verdict_accuracy", min=0.95),),
    )
    passed, _ = gate.evaluate(c)
    assert passed is False


# ---------------------------------------------------------------------------
# Degradation drills
# ---------------------------------------------------------------------------


def test_degradation_thor_demotes_to_shadow_when_vidar_absent() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus, vidar_available=False)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-1",
            }
        )
    )
    # Hard-dep degradation: mutation runs in shadow mode instead.
    assert run.shadow_mode is True
    assert run.state == ActionRunState.SUCCEEDED
    assert run.outcome == "shadow_success"


def test_degradation_thor_demotes_to_shadow_when_saga_absent() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus, saga_available=False)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-2",
            }
        )
    )
    assert run.shadow_mode is True


def test_degradation_forseti_absent_stops_verdicts_but_ingest_survives() -> None:
    """Without Forseti no verdicts are produced, but Huginn keeps ingesting."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    # No Forseti subscribed; only Saga listens on verdicts.
    saga = Saga()
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    # Publish an event: nothing subscribes to it, but that's fine (Kafka
    # retention would catch it in real deployment).
    from fdai.agents.huginn import Huginn

    huginn = Huginn(bus=bus)
    asyncio.run(
        huginn.ingest(
            {
                "id": "evt-1",
                "correlation_id": "c",
                "resource_id": "vm-x",
                "event_type": "restart_needed",
            }
        )
    )
    # No verdicts because Forseti isn't wired.
    assert bus.messages_on("object.verdict") == []
    # Event is on the bus - Kafka-equivalent retention.
    assert len(bus.messages_on("object.event")) == 1


def test_degradation_var_absent_leaves_hil_queue_but_auto_continues() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    # No Var subscribed. HIL action stays HIL_PENDING; auto proceeds.
    hil_run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-hil",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "d1",
            }
        )
    )
    auto_run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-auto",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "d2",
            }
        )
    )
    assert hil_run.state == ActionRunState.HIL_PENDING
    assert auto_run.state == ActionRunState.SUCCEEDED


def test_degradation_publish_from_wrong_owner_is_rejected() -> None:
    """Single-writer invariant: bus refuses wrong-owner publish."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    with pytest.raises(PantheonRegistryError, match="not the owner"):
        asyncio.run(bus.publish("Bragi", "object.verdict", {"x": 1}))


def test_degradation_publish_to_unknown_topic_is_rejected() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    with pytest.raises(PantheonRegistryError, match="no declared owner"):
        asyncio.run(bus.publish("Thor", "object.does-not-exist", {}))
