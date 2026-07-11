"""Cross-vertical arbitration loop: Forseti raises, Odin resolves."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.njord import Njord
from fdai.agents.odin import Odin


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def test_forseti_requests_arbitration_on_conflicting_advice() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    request = asyncio.run(
        forseti.maybe_request_arbitration(
            {
                "correlation_id": "c",
                "resource_id": "vm-1",
                "domain_advice": {"cost": "scale_down", "capacity": "scale_up"},
            }
        )
    )
    assert request is not None
    msgs = bus.messages_on("object.arbitration-request")
    assert len(msgs) == 1
    assert set(msgs[0].payload["domains_in_conflict"]) == {"cost", "capacity"}


def test_forseti_no_arbitration_on_unanimous_advice() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    request = asyncio.run(
        forseti.maybe_request_arbitration(
            {
                "correlation_id": "c",
                "domain_advice": {"cost": "hold", "capacity": "hold"},
            }
        )
    )
    assert request is None
    assert bus.messages_on("object.arbitration-request") == []


def test_forseti_no_arbitration_on_single_domain() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    request = asyncio.run(
        forseti.maybe_request_arbitration(
            {"correlation_id": "c", "domain_advice": {"cost": "scale_down"}}
        )
    )
    assert request is None


def test_odin_resolves_conflict_by_priority() -> None:
    bus = _bus()
    odin = Odin(bus=bus)
    decision = asyncio.run(
        odin.arbitrate({"correlation_id": "c", "domains_in_conflict": ["capacity", "cost"]})
    )
    # cost outranks capacity in the default priority order.
    assert decision.winning_domain == "cost"
    assert decision.losing_domains == ("capacity",)


def test_forseti_records_arbitration_decision() -> None:
    forseti = Forseti()
    asyncio.run(
        forseti.on_typed_message(
            "object.arbitration-decision",
            {"correlation_id": "c", "winning_domain": "cost"},
        )
    )
    assert forseti.arbitrations["c"] == "cost"


def test_arbitration_loop_end_to_end() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    odin = Odin(bus=bus)
    # Wire the runtime subscriptions (Odin <- request, Forseti <- decision).
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)

    # A conflicting-advice event drives the whole loop synchronously
    # (InMemoryBus dispatches subscribers inline).
    asyncio.run(
        forseti.maybe_request_arbitration(
            {
                "correlation_id": "corr-arb",
                "resource_id": "vm-1",
                "domain_advice": {"cost": "scale_down", "capacity": "scale_up"},
            }
        )
    )

    decisions = bus.messages_on("object.arbitration-decision")
    assert len(decisions) == 1
    assert decisions[0].payload["winning_domain"] == "cost"
    assert forseti.arbitrations.get("corr-arb") == "cost"


def test_forseti_arbitrations_map_is_bounded() -> None:
    # arbitrations is keyed by correlation id (one per arbitrated event); a
    # long-lived judge must not leak one entry per correlation forever.
    from fdai.agents.forseti import _MAX_RESOURCES

    forseti = Forseti()
    for i in range(_MAX_RESOURCES + 100):
        forseti._record_arbitration(  # noqa: SLF001
            {"correlation_id": f"c{i}", "winning_domain": "cost"}
        )
    assert len(forseti.arbitrations) == _MAX_RESOURCES
    # The oldest correlations were evicted; the newest is retained.
    assert forseti.arbitrations.get(f"c{_MAX_RESOURCES + 100 - 1}") == "cost"
    assert "c0" not in forseti.arbitrations


# ---------------------------------------------------------------------------
# Cross-domain signal aggregation (Njord cost + Freyr capacity)
# ---------------------------------------------------------------------------


def test_forseti_aggregates_cross_domain_conflict() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    # First signal (cost scale_down) alone: no conflict yet.
    asyncio.run(
        forseti.on_typed_message(
            "object.cost-anomaly",
            {"resource_id": "vm-1", "recommendation": "scale_down"},
        )
    )
    assert bus.messages_on("object.arbitration-request") == []
    # Second signal (capacity scale_up) on the same resource: conflict.
    asyncio.run(
        forseti.on_typed_message(
            "object.capacity-forecast",
            {"resource_id": "vm-1", "recommendation": "scale_up"},
        )
    )
    reqs = bus.messages_on("object.arbitration-request")
    assert len(reqs) == 1
    assert set(reqs[0].payload["domains_in_conflict"]) == {"cost", "capacity"}


def test_forseti_no_conflict_when_capacity_holds() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    asyncio.run(
        forseti.on_typed_message(
            "object.cost-anomaly",
            {"resource_id": "vm-2", "recommendation": "scale_down"},
        )
    )
    asyncio.run(
        forseti.on_typed_message(
            "object.capacity-forecast",
            {"resource_id": "vm-2", "recommendation": "hold"},
        )
    )
    assert bus.messages_on("object.arbitration-request") == []


def test_njord_cost_anomaly_carries_recommendation() -> None:
    bus = _bus()
    njord = Njord(bus=bus, anomaly_ratio=1.5)
    for _ in range(3):
        asyncio.run(njord.ingest_cost_sample(scope="rg", amount_usd=100.0))
    payload = asyncio.run(
        njord.ingest_cost_sample(scope="rg", amount_usd=1000.0, resource_id="vm-9")
    )
    assert payload is not None
    assert payload["recommendation"] == "scale_down"
    assert payload["resource_id"] == "vm-9"


def test_freyr_capacity_forecast_carries_recommendation() -> None:
    bus = _bus()
    freyr = Freyr(bus=bus, scale_up_threshold=0.75)
    asyncio.run(freyr.ingest_utilization(resource_id="vm-1", utilization=0.9))
    msgs = bus.messages_on("object.capacity-forecast")
    assert msgs[-1].payload["recommendation"] == "scale_up"


def test_domain_signals_drive_arbitration_end_to_end() -> None:
    bus = _bus()
    njord = Njord(bus=bus, anomaly_ratio=1.5)
    freyr = Freyr(bus=bus, scale_up_threshold=0.75)
    forseti = Forseti(bus=bus)
    odin = Odin(bus=bus)
    bus.subscribe("object.cost-anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.capacity-forecast", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)

    # Njord: cost anomaly on vm-1 (recommends scale_down).
    for _ in range(3):
        asyncio.run(njord.ingest_cost_sample(scope="s", amount_usd=100.0, resource_id="vm-1"))
    asyncio.run(njord.ingest_cost_sample(scope="s", amount_usd=1000.0, resource_id="vm-1"))
    # Freyr: high utilization on vm-1 (recommends scale_up) -> conflict.
    asyncio.run(freyr.ingest_utilization(resource_id="vm-1", utilization=0.95))

    decisions = bus.messages_on("object.arbitration-decision")
    assert len(decisions) >= 1
    assert decisions[-1].payload["winning_domain"] == "cost"  # cost outranks capacity


# ---------------------------------------------------------------------------
# Multi-objective arbitration (weighted score + HIL on close calls)
# ---------------------------------------------------------------------------


from fdai.agents._framework.arbitration import (  # noqa: E402
    MultiObjectiveArbiter,
    weights_from_priority,
    weights_from_priority_curved,
)


def test_weights_descend_with_priority() -> None:
    weights = weights_from_priority(("resilience", "security", "cost", "capacity"))
    ordered = list(weights.values())
    assert ordered == sorted(ordered, reverse=True)
    assert weights["resilience"] == 1.0
    # Every named domain scores strictly above zero.
    assert all(w > 0 for w in weights.values())


def test_magnitude_overrides_priority() -> None:
    """A high-impact lower-priority domain beats a low-impact higher one."""
    bus = _bus()
    odin = Odin(bus=bus)
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "domains_in_conflict": ["cost", "capacity"],
                "impacts": {"cost": 0.2, "capacity": 1.0},
            }
        )
    )
    # capacity (lower priority) wins because its measured impact dominates.
    assert decision.winning_domain == "capacity"
    assert decision.escalate_hil is False
    assert decision.objective_scores["capacity"] > decision.objective_scores["cost"]


def test_close_call_escalates_to_hil() -> None:
    """A near-tie is handed to HIL, never silently auto-picked."""
    bus = _bus()
    odin = Odin(bus=bus)
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "domains_in_conflict": ["cost", "capacity"],
                # 0.55*0.4 == 0.4*0.55 -> exact tie -> margin 0.
                "impacts": {"cost": 0.4, "capacity": 0.55},
            }
        )
    )
    assert decision.escalate_hil is True
    assert decision.margin < 0.10
    assert "close_call" in decision.reason


def test_unknown_domain_escalates_to_hil() -> None:
    arbiter = MultiObjectiveArbiter()
    outcome = arbiter.resolve(("cost", "exotic_domain"))
    assert outcome.escalate_hil is True
    assert "unknown_domain" in outcome.reason


def test_priority_fallback_when_no_impacts() -> None:
    """Absent impacts, the arbiter reproduces the legacy priority winner."""
    arbiter = MultiObjectiveArbiter()
    outcome = arbiter.resolve(("capacity", "cost"))
    assert outcome.winner == "cost"
    assert outcome.losers == ("capacity",)
    assert outcome.escalate_hil is False
    assert outcome.reason.startswith("priority_order")


def test_decision_carries_objective_scores_over_bus() -> None:
    bus = _bus()
    odin = Odin(bus=bus)
    asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "domains_in_conflict": ["cost", "capacity"],
                "impacts": {"cost": 0.9, "capacity": 0.3},
            }
        )
    )
    payload = bus.messages_on("object.arbitration-decision")[-1].payload
    assert "objective_scores" in payload
    assert "margin" in payload
    assert payload["escalate_hil"] is False


def test_forseti_forwards_impacts_from_signals() -> None:
    """Njord ratio and Freyr util become impact magnitudes on the request."""
    bus = _bus()
    forseti = Forseti(bus=bus)
    asyncio.run(
        forseti.on_typed_message(
            "object.cost-anomaly",
            {"resource_id": "vm-1", "recommendation": "scale_down", "ratio": 2.0},
        )
    )
    asyncio.run(
        forseti.on_typed_message(
            "object.capacity-forecast",
            {
                "resource_id": "vm-1",
                "recommendation": "scale_up",
                "forecast_util": 0.9,
            },
        )
    )
    req = bus.messages_on("object.arbitration-request")[-1].payload
    assert req["impacts"]["cost"] == 1.0  # ratio 2.0 -> impact 1.0
    assert req["impacts"]["capacity"] == 0.9


def test_njord_publishes_normalized_impact_on_anomaly() -> None:
    """Njord owns cost normalization: attaches impact = clamp(ratio - 1, 0, 1)."""
    bus = _bus()
    njord = Njord(bus=bus, anomaly_ratio=1.5)
    for _ in range(3):
        asyncio.run(njord.ingest_cost_sample(scope="rg", amount_usd=100.0))
    payload = asyncio.run(
        njord.ingest_cost_sample(scope="rg", amount_usd=200.0, resource_id="vm-9")
    )
    assert payload is not None
    # ratio = 200 / 100 = 2.0 -> impact = 1.0 (full severity).
    assert payload["ratio"] == 2.0
    assert payload["impact"] == 1.0
    published = bus.messages_on("object.cost-anomaly")[-1].payload
    assert published["impact"] == 1.0


def test_njord_impact_scales_with_moderate_overspend() -> None:
    """A 1.6x overspend normalizes to a 0.6 impact (partial severity)."""
    import pytest

    bus = _bus()
    njord = Njord(bus=bus, anomaly_ratio=1.5)
    for _ in range(3):
        asyncio.run(njord.ingest_cost_sample(scope="rg", amount_usd=100.0))
    payload = asyncio.run(
        njord.ingest_cost_sample(scope="rg", amount_usd=160.0, resource_id="vm-9")
    )
    assert payload is not None
    assert payload["impact"] == pytest.approx(0.6)


def test_freyr_publishes_normalized_impact_on_forecast() -> None:
    """Freyr owns capacity normalization: attaches impact = clamp(forecast_util)."""
    bus = _bus()
    freyr = Freyr(bus=bus, scale_up_threshold=0.75)
    asyncio.run(freyr.ingest_utilization(resource_id="vm-1", utilization=0.9))
    payload = bus.messages_on("object.capacity-forecast")[-1].payload
    # smoothed(alpha=0.3, prev=0.9) starts equal to first sample -> 0.9.
    assert payload["forecast_util"] == payload["impact"]
    assert 0.0 <= payload["impact"] <= 1.0


def test_forseti_prefers_specialist_impact_over_raw_ratio() -> None:
    """When both `impact` and legacy `ratio` are present, the explicit wins."""
    bus = _bus()
    forseti = Forseti(bus=bus)
    asyncio.run(
        forseti.on_typed_message(
            "object.cost-anomaly",
            {
                "resource_id": "vm-1",
                "recommendation": "scale_down",
                "ratio": 10.0,  # legacy fallback would give impact 1.0
                "impact": 0.25,  # specialist says this is a mild signal
            },
        )
    )
    asyncio.run(
        forseti.on_typed_message(
            "object.capacity-forecast",
            {
                "resource_id": "vm-1",
                "recommendation": "scale_up",
                "impact": 0.9,
            },
        )
    )
    req = bus.messages_on("object.arbitration-request")[-1].payload
    assert req["impacts"]["cost"] == 0.25
    assert req["impacts"]["capacity"] == 0.9


# ---------------------------------------------------------------------------
# Hardening: corrupt-input defenses (rubric critique)
# ---------------------------------------------------------------------------


def test_nan_impact_escalates_to_hil_not_corrupt_sort() -> None:
    """A NaN impact must not silently win or corrupt the ranking."""
    arbiter = MultiObjectiveArbiter()
    outcome = arbiter.resolve(("cost", "capacity"), {"cost": float("nan"), "capacity": 0.5})
    assert outcome.escalate_hil is True
    assert "nonfinite_impact" in outcome.reason
    # A corrupt impact scores as zero, never NaN.
    assert outcome.objective_scores["cost"] == 0.0


def test_inf_impact_escalates_to_hil() -> None:
    arbiter = MultiObjectiveArbiter()
    outcome = arbiter.resolve(("cost", "capacity"), {"capacity": float("inf")})
    assert outcome.escalate_hil is True
    assert "nonfinite_impact" in outcome.reason


def test_non_numeric_impact_is_treated_as_corrupt() -> None:
    arbiter = MultiObjectiveArbiter()
    outcome = arbiter.resolve(("cost", "capacity"), {"cost": "oops"})  # type: ignore[dict-item]
    assert outcome.escalate_hil is True
    assert "nonfinite_impact" in outcome.reason


def test_duplicate_domains_never_place_winner_in_losers() -> None:
    arbiter = MultiObjectiveArbiter()
    outcome = arbiter.resolve(("cost", "cost"))
    assert outcome.winner == "cost"
    assert "cost" not in outcome.losers
    assert outcome.losers == ()


def test_negative_weight_config_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="finite and >= 0"):
        MultiObjectiveArbiter(weights={"cost": -1.0})


def test_non_finite_weight_config_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="finite and >= 0"):
        MultiObjectiveArbiter(weights={"cost": float("inf")})


def test_forseti_clears_advice_after_arbitration() -> None:
    # H7: once a conflict is surfaced, the accumulated advice must be
    # consumed - otherwise the stale opposing recommendation re-triggers a
    # duplicate arbitration on the next signal, and the maps leak.
    bus = _bus()
    forseti = Forseti()
    forseti.bind_bus(bus)

    async def _run() -> int:
        await forseti._ingest_domain_signal(
            "cost", {"resource_id": "vm-1", "recommendation": "scale_down"}
        )
        await forseti._ingest_domain_signal(
            "capacity", {"resource_id": "vm-1", "recommendation": "scale_up"}
        )
        # Conflict surfaced -> advice consumed for vm-1.
        assert "vm-1" not in forseti._domain_advice
        assert "vm-1" not in forseti._domain_impact
        before = len(bus.messages_on("object.arbitration-request"))
        # A fresh single signal must NOT immediately re-fire an arbitration.
        await forseti._ingest_domain_signal(
            "cost", {"resource_id": "vm-1", "recommendation": "scale_down"}
        )
        after = len(bus.messages_on("object.arbitration-request"))
        return after - before

    assert asyncio.run(_run()) == 0  # no duplicate arbitration


# ---------------------------------------------------------------------------
# Pluggable weight function (issue #2)
# ---------------------------------------------------------------------------


def test_curved_linear_matches_default() -> None:
    """`linear` curve reproduces the default `weights_from_priority` exactly."""
    priority = ("resilience", "security", "change_safety", "cost", "capacity")
    linear = weights_from_priority(priority)
    curved = weights_from_priority_curved(priority, curve="linear")
    assert curved == linear


def test_curved_convex_widens_top_gap() -> None:
    """A convex curve puts more distance between top-1 and top-2."""
    priority = ("resilience", "security", "change_safety", "cost", "capacity")
    linear = weights_from_priority_curved(priority, curve="linear")
    convex = weights_from_priority_curved(priority, curve="convex", convexity=2.0)
    # Top and bottom anchors are preserved (calibration).
    assert convex[priority[0]] == 1.0
    assert convex[priority[-1]] == linear[priority[-1]]
    # A convex curve puts the second priority CLOSER to top-1 (weight
    # advantage over the rest grows), so the linear gap is smaller here.
    assert convex[priority[1]] > linear[priority[1]]
    # Weights are still monotonically non-increasing along priority.
    values = [convex[p] for p in priority]
    assert values == sorted(values, reverse=True)


def test_curved_concave_flattens_top_gap() -> None:
    """A concave curve narrows the advantage of the top priority."""
    priority = ("resilience", "security", "change_safety", "cost", "capacity")
    linear = weights_from_priority_curved(priority, curve="linear")
    concave = weights_from_priority_curved(priority, curve="concave", convexity=0.5)
    assert concave[priority[0]] == 1.0
    assert concave[priority[-1]] == linear[priority[-1]]
    # A concave curve drops the second priority further from top-1.
    assert concave[priority[1]] < linear[priority[1]]
    values = [concave[p] for p in priority]
    assert values == sorted(values, reverse=True)


def test_curved_rejects_unknown_curve_name() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown curve"):
        weights_from_priority_curved(("a", "b"), curve="wobbly")


def test_curved_rejects_invalid_convexity() -> None:
    import pytest

    with pytest.raises(ValueError, match="convex curve requires"):
        weights_from_priority_curved(("a", "b"), curve="convex", convexity=1.0)
    with pytest.raises(ValueError, match="concave curve requires"):
        weights_from_priority_curved(("a", "b"), curve="concave", convexity=1.5)


def test_arbiter_accepts_weight_fn_callable() -> None:
    """A fork can supply any pure function from priority to weights."""
    priority = ("resilience", "security", "change_safety", "cost", "capacity")

    def convex_fn(p: tuple[str, ...]) -> dict[str, float]:
        return weights_from_priority_curved(p, curve="convex", convexity=2.5)

    arbiter = MultiObjectiveArbiter(priority=priority, weight_fn=convex_fn)
    assert arbiter.weights == convex_fn(priority)


def test_arbiter_rejects_weights_and_weight_fn_together() -> None:
    import pytest

    with pytest.raises(ValueError, match="either 'weights' or 'weight_fn'"):
        MultiObjectiveArbiter(
            weights={"cost": 0.5},
            weight_fn=lambda p: {"cost": 0.5},
        )


def test_arbiter_rejects_non_dict_weight_fn_output() -> None:
    import pytest

    def bad_fn(p: tuple[str, ...]) -> dict[str, float]:
        return [("cost", 0.5)]  # type: ignore[return-value]

    with pytest.raises(ValueError, match="must return a dict"):
        MultiObjectiveArbiter(weight_fn=bad_fn)


def test_arbiter_validates_weight_fn_output_finiteness() -> None:
    """A weight_fn that returns a NaN/negative weight fails at construction."""
    import pytest

    with pytest.raises(ValueError, match="finite and >= 0"):
        MultiObjectiveArbiter(weight_fn=lambda p: {"cost": float("nan")})
    with pytest.raises(ValueError, match="finite and >= 0"):
        MultiObjectiveArbiter(weight_fn=lambda p: {"cost": -0.5})


def test_convex_arbiter_still_picks_priority_winner_on_equal_impact() -> None:
    """A curved config still reproduces priority-order winner with equal impacts."""
    priority = ("resilience", "security", "change_safety", "cost", "capacity")
    arbiter = MultiObjectiveArbiter(
        priority=priority,
        weight_fn=lambda p: weights_from_priority_curved(p, curve="convex", convexity=2.5),
    )
    outcome = arbiter.resolve(("cost", "capacity"))
    assert outcome.winner == "cost"  # cost outranks capacity
    assert outcome.escalate_hil is False


# ---------------------------------------------------------------------------
# Temporal / stateful fairness (issue #4)
# ---------------------------------------------------------------------------


from fdai.agents._framework.arbitration import (  # noqa: E402
    AlternatingFairnessPolicy,
    HysteresisPolicy,
    RecentDecision,
    TemporalPolicy,
)
from fdai.agents.odin import DecisionHistory, NoopDecisionHistory  # noqa: E402


def _history(*winners: str, resource_id: str = "vm-1") -> tuple[RecentDecision, ...]:
    """Build a chronological history where each entry beats the other domain."""
    other = "capacity" if winners and winners[0] == "cost" else "cost"
    out: list[RecentDecision] = []
    for i, w in enumerate(winners):
        loser = "cost" if w == "capacity" else other
        out.append(
            RecentDecision(
                winner=w,
                losers=(loser,),
                resource_id=resource_id,
                at=float(i),
            )
        )
    return tuple(out)


def test_empty_history_reproduces_stateless_decision() -> None:
    """No history + no policy == today's stateless resolve, exactly."""
    arbiter = MultiObjectiveArbiter()
    baseline = arbiter.resolve(("cost", "capacity"), {"cost": 0.9, "capacity": 0.3})
    with_empty = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.9, "capacity": 0.3},
        history=(),
        policy=AlternatingFairnessPolicy(streak_threshold=3),
    )
    assert baseline.winner == with_empty.winner == "cost"
    assert baseline.objective_scores == with_empty.objective_scores


def test_alternating_fairness_short_streak_does_not_flip() -> None:
    """Two prior wins do not clear the default threshold of three."""
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.5)
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.6, "capacity": 0.55},
        history=_history("cost", "cost"),  # only 2 in a row
        policy=policy,
    )
    # Below threshold -> policy is a no-op, cost still wins on score.
    assert outcome.winner == "cost"
    assert "policy=" not in outcome.reason


def test_alternating_fairness_flips_after_threshold_streak() -> None:
    """After three same-domain wins the perpetual loser gets a boost."""
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.5)
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.6, "capacity": 0.55},
        history=_history("cost", "cost", "cost"),
        policy=policy,
    )
    # Boost pushed capacity above cost. HIL band might catch the flip if
    # the margin is tight, but the perpetual winner MUST NOT keep winning.
    assert outcome.winner == "capacity"
    assert "policy=alternating_fairness" in outcome.reason


def test_alternating_fairness_streak_resets_on_intervening_win() -> None:
    """A single opposing win breaks the streak; no boost applies."""
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.5)
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.6, "capacity": 0.55},
        history=_history("cost", "cost", "capacity", "cost"),
        policy=policy,
    )
    # Most recent contiguous streak is cost=1 -> below threshold.
    assert outcome.winner == "cost"


def test_alternating_fairness_ignores_unrelated_winners() -> None:
    """A prior winner not in the current conflict is not counted."""
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.5)
    unrelated = (
        RecentDecision(winner="resilience", losers=("security",), resource_id="vm-1", at=0.0),
        RecentDecision(winner="resilience", losers=("security",), resource_id="vm-1", at=1.0),
        RecentDecision(winner="resilience", losers=("security",), resource_id="vm-1", at=2.0),
    )
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.6, "capacity": 0.55},
        history=unrelated,
        policy=policy,
    )
    # Zero relevant history for a cost/capacity conflict -> stateless behavior.
    assert outcome.winner == "cost"


def test_hysteresis_dampens_flapping_between_two_domains() -> None:
    """Alternating winners in the window give the last winner a bonus."""
    # Equal weights so the arithmetic is purely impact + bonus driven.
    arbiter = MultiObjectiveArbiter(weights={"cost": 0.5, "capacity": 0.5})
    policy = HysteresisPolicy(window=4, bonus=0.5)
    # Baseline (no policy): capacity's stronger impact wins.
    baseline = arbiter.resolve(("cost", "capacity"), {"cost": 0.60, "capacity": 0.80})
    assert baseline.winner == "capacity"
    # With flapping history whose most-recent winner is cost, hysteresis
    # boosts cost's weight enough to hold onto the win.
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.60, "capacity": 0.80},
        history=_history("capacity", "cost", "capacity", "cost"),
        policy=policy,
    )
    assert outcome.winner == "cost"
    assert "policy=hysteresis" in outcome.reason


def test_hysteresis_no_bonus_on_one_sided_streak() -> None:
    """A stable one-sided run of winners is not flapping - no bonus applies."""
    arbiter = MultiObjectiveArbiter(weights={"cost": 0.5, "capacity": 0.5})
    policy = HysteresisPolicy(window=4, bonus=0.5)
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.60, "capacity": 0.80},
        history=_history("cost", "cost", "cost", "cost"),
        policy=policy,
    )
    # Not flapping -> hysteresis is a no-op -> capacity wins on impact.
    assert outcome.winner == "capacity"


def test_temporal_policy_does_not_weaken_hil_escalation() -> None:
    """A boost that lands the margin inside the HIL band still escalates."""
    # Equal weights so we can steer the outcome purely with a small boost.
    arbiter = MultiObjectiveArbiter(weights={"cost": 1.0, "capacity": 1.0})
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.2)
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.60, "capacity": 0.50},
        history=_history("cost", "cost", "cost"),
        policy=policy,
    )
    # Baseline scores: cost=0.60, capacity=0.50 (margin 0.166, auto).
    # After boost: capacity weight=1.2, capacity score=0.60 - exact tie.
    # An exact tie is deep inside the HIL band; escalation MUST stand.
    assert outcome.escalate_hil is True
    assert "close_call" in outcome.reason


def test_policy_returning_negative_weight_is_rejected() -> None:
    """A buggy policy MUST NOT corrupt scoring."""
    import pytest

    class BadPolicy(TemporalPolicy):
        name = "bad"

        def adjust(self, *, base_weights, domains, history):  # type: ignore[no-untyped-def]
            return {"cost": -1.0, "capacity": 0.5}

    arbiter = MultiObjectiveArbiter()
    with pytest.raises(ValueError, match="invalid weight"):
        arbiter.resolve(
            ("cost", "capacity"),
            {"cost": 0.6, "capacity": 0.55},
            history=_history("cost", "cost", "cost"),
            policy=BadPolicy(),
        )


def test_policy_returning_non_dict_is_rejected() -> None:
    import pytest

    class BadPolicy(TemporalPolicy):
        name = "bad"

        def adjust(self, *, base_weights, domains, history):  # type: ignore[no-untyped-def]
            return [("cost", 0.5)]  # type: ignore[return-value]

    arbiter = MultiObjectiveArbiter()
    with pytest.raises(ValueError, match="MUST return a non-empty dict"):
        arbiter.resolve(
            ("cost", "capacity"),
            {"cost": 0.6, "capacity": 0.55},
            history=(),
            policy=BadPolicy(),
        )


def test_alternating_fairness_config_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="streak_threshold MUST be >= 2"):
        AlternatingFairnessPolicy(streak_threshold=1)
    with pytest.raises(ValueError, match="boost MUST be finite and > 0"):
        AlternatingFairnessPolicy(boost=0.0)
    with pytest.raises(ValueError, match="boost MUST be finite and > 0"):
        AlternatingFairnessPolicy(boost=float("inf"))


def test_hysteresis_config_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="window MUST be >= 2"):
        HysteresisPolicy(window=1)
    with pytest.raises(ValueError, match="bonus MUST be finite and > 0"):
        HysteresisPolicy(bonus=-0.1)


def test_same_history_and_input_produce_same_decision() -> None:
    """Determinism: same history + same input => same decision, always."""
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=2, boost=0.2)
    history = _history("cost", "cost")
    impacts = {"cost": 0.7, "capacity": 0.5}
    first = arbiter.resolve(("cost", "capacity"), impacts, history=history, policy=policy)
    for _ in range(50):
        again = arbiter.resolve(("cost", "capacity"), impacts, history=history, policy=policy)
        assert again == first


# ---------------------------------------------------------------------------
# Odin integration: DecisionHistory seam + policy wiring
# ---------------------------------------------------------------------------


class _FakeHistory(DecisionHistory):
    """Deterministic in-memory history for tests."""

    def __init__(self, records: dict[str, tuple[RecentDecision, ...]]) -> None:
        self._records = records
        self.calls: list[tuple[str, int]] = []

    async def recent(self, resource_id: str, *, limit: int) -> tuple[RecentDecision, ...]:
        self.calls.append((resource_id, limit))
        return self._records.get(resource_id, ())[:limit]


def test_odin_defaults_to_noop_history_and_no_policy() -> None:
    """Upstream default reproduces stateless behavior exactly."""
    odin = Odin()
    assert isinstance(odin._history, NoopDecisionHistory)
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "resource_id": "vm-1",
                "domains_in_conflict": ["cost", "capacity"],
                "impacts": {"cost": 0.6, "capacity": 0.55},
            }
        )
    )
    assert decision.winning_domain == "cost"


def test_odin_temporal_policy_without_history_seam_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="DecisionHistory was injected"):
        Odin(temporal_policy=AlternatingFairnessPolicy(streak_threshold=3))


def test_odin_history_window_validated() -> None:
    import pytest

    with pytest.raises(ValueError, match="history_window MUST be positive"):
        Odin(history_window=0)


def test_odin_fetches_history_and_applies_policy() -> None:
    """End-to-end: streak history + policy flips the arbitration outcome."""
    bus = _bus()
    history = _FakeHistory({"vm-1": _history("cost", "cost", "cost", resource_id="vm-1")})
    odin = Odin(
        bus=bus,
        temporal_policy=AlternatingFairnessPolicy(streak_threshold=3, boost=0.5),
        history=history,
        history_window=5,
    )
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "resource_id": "vm-1",
                "domains_in_conflict": ["cost", "capacity"],
                "impacts": {"cost": 0.6, "capacity": 0.55},
            }
        )
    )
    assert decision.winning_domain == "capacity"
    # History was consulted with the configured window.
    assert history.calls == [("vm-1", 5)]
    # Grounding for the audit log.
    payload = bus.messages_on("object.arbitration-decision")[-1].payload
    assert payload["history_considered"] == 3
    assert "policy=alternating_fairness" in payload["reason"]


def test_odin_skips_history_lookup_when_no_resource_id() -> None:
    """A resource-less arbitration falls through to stateless behavior."""
    history = _FakeHistory({"": _history("cost", "cost", "cost")})
    odin = Odin(
        temporal_policy=AlternatingFairnessPolicy(streak_threshold=3, boost=0.5),
        history=history,
    )
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                # No resource_id.
                "domains_in_conflict": ["cost", "capacity"],
                "impacts": {"cost": 0.6, "capacity": 0.55},
            }
        )
    )
    assert decision.winning_domain == "cost"
    assert history.calls == []  # never asked


# ---------------------------------------------------------------------------
# Hardening: latent-bug regressions found in the critique-10 sweep
# ---------------------------------------------------------------------------


def test_corrupt_impact_on_one_domain_escalates_not_silently_wins() -> None:
    """H2: a non-numeric impact must not be silently dropped.

    Previously ``_coerce_impacts`` dropped ``{'cost': 'oops'}`` from the
    dict, then the arbiter defaulted cost's impact to ``1.0`` (full
    weight) and cost silently won. That is a fail-open path on a corrupt
    signal - the whole call MUST escalate to HIL instead.
    """
    odin = Odin()
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "resource_id": "vm-1",
                "domains_in_conflict": ["cost", "capacity"],
                # cost is corrupt; capacity is valid.
                "impacts": {"cost": "oops", "capacity": 0.9},
            }
        )
    )
    assert decision.escalate_hil is True
    assert "nonfinite_impact" in decision.reason


def test_none_impact_is_treated_as_corrupt_not_dropped() -> None:
    """A ``None`` impact is corrupt (unmeasured), not 'absent' (default 1.0)."""
    odin = Odin()
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "resource_id": "vm-1",
                "domains_in_conflict": ["cost", "capacity"],
                "impacts": {"cost": None, "capacity": 0.5},
            }
        )
    )
    assert decision.escalate_hil is True
    assert "nonfinite_impact" in decision.reason


def test_alternating_fairness_does_not_count_unrelated_loser_pairs() -> None:
    """Semantic drift fix: past cost-vs-resilience wins are not a cost streak
    against capacity today. Winner-and-loser overlap with today's domains
    is required, not just winner overlap.
    """
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.5)
    # Three past cost wins - but all against 'resilience', not 'capacity'.
    unrelated_streak = (
        RecentDecision(winner="cost", losers=("resilience",), resource_id="vm-1", at=0.0),
        RecentDecision(winner="cost", losers=("resilience",), resource_id="vm-1", at=1.0),
        RecentDecision(winner="cost", losers=("resilience",), resource_id="vm-1", at=2.0),
    )
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.6, "capacity": 0.55},
        history=unrelated_streak,
        policy=policy,
    )
    # Cost's streak against a different loser MUST NOT feed the fairness
    # boost against capacity - the pair never repeated.
    assert outcome.winner == "cost"
    assert "policy=" not in outcome.reason


def test_alternating_fairness_counts_multi_way_conflicts_with_overlap() -> None:
    """A three-way past conflict counts when its loser set overlaps today's."""
    arbiter = MultiObjectiveArbiter()
    policy = AlternatingFairnessPolicy(streak_threshold=3, boost=0.5)
    # Past three-way conflicts where cost won over (capacity, resilience).
    three_way_streak = (
        RecentDecision(
            winner="cost", losers=("capacity", "resilience"), resource_id="vm-1", at=0.0
        ),
        RecentDecision(
            winner="cost", losers=("capacity", "resilience"), resource_id="vm-1", at=1.0
        ),
        RecentDecision(
            winner="cost", losers=("capacity", "resilience"), resource_id="vm-1", at=2.0
        ),
    )
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.6, "capacity": 0.55},
        history=three_way_streak,
        policy=policy,
    )
    # capacity is in the past losers -> streak counts -> boost flips winner.
    assert outcome.winner == "capacity"
    assert "policy=alternating_fairness" in outcome.reason


def test_hysteresis_does_not_flap_on_unrelated_loser_pairs() -> None:
    """Pair-relevance guard applies to hysteresis too."""
    arbiter = MultiObjectiveArbiter(weights={"cost": 0.5, "capacity": 0.5})
    policy = HysteresisPolicy(window=4, bonus=0.5)
    # Past 'flapping' between cost and capacity, but every entry pairs
    # cost with 'resilience' (unrelated loser). Not a real flap for today's
    # cost-vs-capacity conflict.
    fake_flap = (
        RecentDecision(winner="capacity", losers=("resilience",), resource_id="vm-1", at=0.0),
        RecentDecision(winner="cost", losers=("resilience",), resource_id="vm-1", at=1.0),
        RecentDecision(winner="capacity", losers=("resilience",), resource_id="vm-1", at=2.0),
        RecentDecision(winner="cost", losers=("resilience",), resource_id="vm-1", at=3.0),
    )
    outcome = arbiter.resolve(
        ("cost", "capacity"),
        {"cost": 0.60, "capacity": 0.80},
        history=fake_flap,
        policy=policy,
    )
    # No overlap on losers -> no relevant history -> capacity wins on impact.
    assert outcome.winner == "capacity"


def test_alternating_fairness_boost_upper_bound_enforced() -> None:
    """A runaway boost > 1.0 is a config error, not silently accepted."""
    import pytest

    with pytest.raises(ValueError, match="boost MUST be <= 1.0"):
        AlternatingFairnessPolicy(boost=1.5)


def test_hysteresis_bonus_upper_bound_enforced() -> None:
    import pytest

    with pytest.raises(ValueError, match="bonus MUST be <= 1.0"):
        HysteresisPolicy(bonus=2.0)


def test_odin_forwards_weight_fn_seam_from_pull_request_2() -> None:
    """M4: Odin now propagates weight_fn so a fork can use a curved config."""
    priority = ("resilience", "security", "change_safety", "cost", "capacity")
    odin = Odin(
        priority=priority,
        weight_fn=lambda p: weights_from_priority_curved(p, curve="convex", convexity=2.5),
    )
    # The arbiter it built MUST reflect the curved weights, not linear defaults.
    expected = weights_from_priority_curved(priority, curve="convex", convexity=2.5)
    assert odin._arbiter.weights == expected


def test_odin_rejects_weights_and_weight_fn_together() -> None:
    """Config-ambiguity guard flows through Odin."""
    import pytest

    with pytest.raises(ValueError, match="either 'weights' or 'weight_fn'"):
        Odin(
            weights={"cost": 0.5, "capacity": 0.5},
            weight_fn=lambda p: {"cost": 0.5, "capacity": 0.5},
        )
