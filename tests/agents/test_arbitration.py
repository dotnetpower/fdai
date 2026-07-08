"""Cross-vertical arbitration loop: Forseti raises, Odin resolves."""

from __future__ import annotations

import asyncio

from fdai.agents.bus import InMemoryBus
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.njord import Njord
from fdai.agents.odin import Odin
from fdai.agents.registry import load_pantheon


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


from fdai.agents.arbitration import (  # noqa: E402
    MultiObjectiveArbiter,
    weights_from_priority,
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
