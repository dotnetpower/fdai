"""Wave 5 domain-specialist tests."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.freyr import _MAX_SAMPLES as _FREYR_MAX_SAMPLES
from fdai.agents.freyr import Freyr
from fdai.agents.loki import Loki
from fdai.agents.njord import _MAX_SAMPLES as _NJORD_MAX_SAMPLES
from fdai.agents.njord import Njord

# ---------------------------------------------------------------------------
# Njord
# ---------------------------------------------------------------------------


def test_njord_emits_anomaly_when_spend_exceeds_baseline() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    n = Njord(bus=bus, anomaly_ratio=1.5)
    # Prime baseline
    for _ in range(10):
        asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=100.0))
    # Spike
    asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=200.0))
    anomalies = bus.messages_on("object.cost-anomaly")
    assert len(anomalies) == 1
    payload = anomalies[0].payload
    assert payload["scope"] == "rg-1"
    assert payload["ratio"] >= 1.5


def test_njord_no_anomaly_within_baseline() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    n = Njord(bus=bus, anomaly_ratio=1.5)
    for _ in range(10):
        asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=100.0))
    asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=120.0))
    assert bus.messages_on("object.cost-anomaly") == []


def test_njord_advisory_publication_is_rate_limited() -> None:
    """The cost-anomaly advisory is a discretionary proposal, so it honors the
    declared rate_limits (agent-pantheon.md 7.9): over-budget advisories are
    dropped and recorded, never shed silently."""
    from fdai.agents._framework.rate_limiter import RateLimiter

    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    n = Njord(bus=bus, anomaly_ratio=1.5)
    # Clock-frozen budget of 2 proposals/minute so the third is throttled.
    n._proposal_limiter = RateLimiter(per_minute=2, per_hour=100, now=lambda: 0.0)
    # Three distinct scopes each spike once -> three anomalies attempted.
    for scope in ("rg-a", "rg-b", "rg-c"):
        for _ in range(3):
            asyncio.run(n.ingest_cost_sample(scope=scope, amount_usd=100.0))
        asyncio.run(n.ingest_cost_sample(scope=scope, amount_usd=1000.0))
    assert len(bus.messages_on("object.cost-anomaly")) == 2
    assert n.behavior_snapshot().get("rate_limit_exceeded") == 1


def test_njord_cost_impact_returns_table_value() -> None:
    n = Njord()
    est = n.cost_impact("remediate.enable-encryption")
    assert est.monthly_delta_usd == 3.5
    assert est.confidence >= 0.5


def test_njord_cost_impact_defaults_low_confidence_for_unknown() -> None:
    n = Njord()
    est = n.cost_impact("unknown.thing")
    assert est.monthly_delta_usd == 0.0
    assert est.confidence < 0.5


def test_njord_introspect_scopes_to_named_scope() -> None:
    # A single-token scope name ("rg-1") is what the introspection
    # tokenizer can match; ingest a couple of samples then name it.
    n = Njord()
    asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=100.0))
    asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=120.0))
    result = asyncio.run(n.introspect("what is the cost for rg-1?", {}))
    assert result.facts["scope"] == "rg-1"
    assert result.facts["sample_count"] == 2
    assert result.facts["latest_usd"] == 120.0
    assert "rg-1" in result.answer


def test_njord_introspect_scopes_to_named_action() -> None:
    # A single-token cost-table key so the tokenizer can match it.
    n = Njord(cost_table={"restart": 12.5})
    result = asyncio.run(n.introspect("cost impact of restart?", {}))
    assert result.facts["action_type"] == "restart"
    assert result.facts["monthly_delta_usd"] == 12.5
    assert "restart" in result.answer


def test_njord_introspect_general_when_no_samples() -> None:
    n = Njord()
    result = asyncio.run(n.introspect("what do you track?", {}))
    assert result.facts["tracked_scopes_count"] == 0
    assert "No cost samples" in result.answer


def test_njord_introspect_general_summary_when_scope_unnamed() -> None:
    # Samples exist but the question names neither a scope nor an action,
    # so Njord returns the multi-scope tracking summary.
    n = Njord()
    asyncio.run(n.ingest_cost_sample(scope="rg-9", amount_usd=10.0))
    result = asyncio.run(n.introspect("give me an overview", {}))
    assert result.facts["tracked_scopes_count"] == 1
    assert "Tracking cost for 1 scope" in result.answer


def test_njord_sample_history_is_bounded() -> None:
    # A long-lived cost watcher ingests one sample per billing tick forever;
    # only the tail baseline window is read, so retained samples must not grow
    # without bound.
    n = Njord()
    for i in range(_NJORD_MAX_SAMPLES * 2):
        asyncio.run(n.ingest_cost_sample(scope="rg-soak", amount_usd=100.0 + i))
    assert len(n._samples["rg-soak"]) == _NJORD_MAX_SAMPLES  # noqa: SLF001
    # The tail is preserved (most recent sample is last).
    assert n._samples["rg-soak"][-1] == 100.0 + (_NJORD_MAX_SAMPLES * 2 - 1)  # noqa: SLF001


# ---------------------------------------------------------------------------
# Freyr
# ---------------------------------------------------------------------------


def test_freyr_forecast_recommends_scale_up_on_high_util() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Freyr(bus=bus, scale_up_threshold=0.75)
    for u in (0.6, 0.7, 0.8, 0.85, 0.9):
        asyncio.run(f.ingest_utilization(resource_id="vm-1", utilization=u))
    advice = f.sizing_advice("vm-1")
    assert advice.action == "scale_up"


def test_freyr_recommends_scale_down_on_low_util() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Freyr(bus=bus, scale_down_threshold=0.25)
    for u in (0.3, 0.2, 0.15, 0.1, 0.1):
        asyncio.run(f.ingest_utilization(resource_id="vm-2", utilization=u))
    advice = f.sizing_advice("vm-2")
    assert advice.action == "scale_down"


def test_freyr_publishes_capacity_forecast_events() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Freyr(bus=bus)
    for u in (0.4, 0.5, 0.6):
        asyncio.run(f.ingest_utilization(resource_id="vm-3", utilization=u))
    events = bus.messages_on("object.capacity-forecast")
    assert len(events) == 3
    assert events[-1].payload["resource_id"] == "vm-3"


def test_freyr_sample_history_is_bounded() -> None:
    # The EWMA forecast is the real state; _samples is only read for its tail
    # and length, so a long-lived capacity watcher must not accumulate a
    # sample per tick forever.
    f = Freyr()
    for i in range(_FREYR_MAX_SAMPLES * 2):
        asyncio.run(f.ingest_utilization(resource_id="vm-soak", utilization=0.5))
        _ = i
    assert len(f._samples["vm-soak"]) == _FREYR_MAX_SAMPLES  # noqa: SLF001


# ---------------------------------------------------------------------------
# Loki
# ---------------------------------------------------------------------------


def test_loki_respects_blast_radius_cap() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=2)
    proposal = asyncio.run(
        loki.propose_experiment(
            experiment_id="ex-1",
            action_type="ops.restart-service",
            targets=("a", "b", "c", "d"),
        )
    )
    assert proposal.accepted
    assert len(proposal.targets) == 2
    events = bus.messages_on("object.chaos-experiment")
    assert events[0].payload["blast_radius_used"] == 2


def test_loki_refuses_further_proposals_when_radius_full() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=1)
    asyncio.run(
        loki.propose_experiment(
            experiment_id="ex-1",
            action_type="x.y",
            targets=("t1",),
        )
    )
    second = asyncio.run(
        loki.propose_experiment(
            experiment_id="ex-2",
            action_type="x.y",
            targets=("t2",),
        )
    )
    assert not second.accepted
    assert second.reason == "blast_radius_full"


def test_loki_release_targets_frees_slots() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=1)
    asyncio.run(loki.propose_experiment(experiment_id="e1", action_type="x", targets=("t1",)))
    loki.release_targets(("t1",))
    third = asyncio.run(
        loki.propose_experiment(experiment_id="e2", action_type="x", targets=("t2",))
    )
    assert third.accepted


def test_loki_proposals_log_is_bounded() -> None:
    # Loki appends one entry per proposal forever; the log is only read for
    # recent diagnostics, so it must be a bounded ring rather than an
    # unbounded list on a long-running scheduler.
    from fdai.agents.loki import _MAX_PROPOSALS

    loki = Loki(blast_radius_cap=1)
    for i in range(_MAX_PROPOSALS + 50):
        asyncio.run(
            loki.propose_experiment(experiment_id=f"e{i}", action_type="x", targets=(f"t{i}",))
        )
    assert len(loki.proposals) == _MAX_PROPOSALS
