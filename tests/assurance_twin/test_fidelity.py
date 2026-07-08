"""SimulationFidelityLedger - what-if predictions measured against reality.

Covers the fidelity contract: join predicted vs actual by id, accumulate
per-key MAE / MAPE / within-tolerance rate, order-independent joining,
zero-actual handling, memory-bounded eviction, and is_reliable as a fail-
closed promotion signal.
"""

from __future__ import annotations

import math

import pytest

from fdai.core.assurance_twin import SimulationFidelityLedger


def test_prediction_then_actual_joins() -> None:
    led = SimulationFidelityLedger(tolerance=0.2)
    led.record_prediction("p1", key="cost.resize", predicted=100.0)
    led.record_actual("p1", actual=110.0)
    stat = led.stat("cost.resize")
    assert stat is not None
    assert stat.samples == 1
    assert stat.mae == 10.0
    assert math.isclose(stat.mape, 10.0 / 110.0)
    assert stat.within_tolerance_rate == 1.0  # 9% within 20%


def test_actual_before_prediction_also_joins() -> None:
    led = SimulationFidelityLedger()
    led.record_actual("p1", actual=50.0)
    led.record_prediction("p1", key="k", predicted=50.0)
    stat = led.stat("k")
    assert stat is not None
    assert stat.mae == 0.0
    assert stat.mape == 0.0


def test_out_of_tolerance_lowers_rate() -> None:
    led = SimulationFidelityLedger(tolerance=0.1)
    led.record_prediction("p1", key="k", predicted=100.0)
    led.record_actual("p1", actual=200.0)  # 50% error > 10%
    stat = led.stat("k")
    assert stat is not None
    assert stat.within_tolerance_rate == 0.0


def test_zero_actual_exact_prediction_is_perfect() -> None:
    led = SimulationFidelityLedger()
    led.record_prediction("p1", key="k", predicted=0.0)
    led.record_actual("p1", actual=0.0)
    stat = led.stat("k")
    assert stat is not None
    assert stat.mape == 0.0


def test_zero_actual_nonzero_prediction_is_max_error() -> None:
    led = SimulationFidelityLedger()
    led.record_prediction("p1", key="k", predicted=5.0)
    led.record_actual("p1", actual=0.0)
    stat = led.stat("k")
    assert stat is not None
    assert stat.mape == 1.0


def test_is_reliable_fails_closed_below_min_samples() -> None:
    led = SimulationFidelityLedger()
    led.record_prediction("p1", key="k", predicted=10.0)
    led.record_actual("p1", actual=10.0)
    # Perfect but only 1 sample -> not judgeable.
    assert led.is_reliable("k", min_samples=5, max_mape=0.2) is False


def test_is_reliable_true_when_accurate() -> None:
    led = SimulationFidelityLedger()
    for i in range(10):
        led.record_prediction(f"p{i}", key="k", predicted=100.0)
        led.record_actual(f"p{i}", actual=102.0)  # 2% error
    assert led.is_reliable("k", min_samples=5, max_mape=0.05) is True


def test_is_reliable_false_when_drifted() -> None:
    led = SimulationFidelityLedger()
    for i in range(10):
        led.record_prediction(f"p{i}", key="k", predicted=100.0)
        led.record_actual(f"p{i}", actual=180.0)  # 44% error
    assert led.is_reliable("k", min_samples=5, max_mape=0.1) is False


def test_pending_eviction_is_bounded() -> None:
    led = SimulationFidelityLedger(max_pending=2)
    led.record_prediction("a", key="k", predicted=1.0)
    led.record_prediction("b", key="k", predicted=1.0)
    led.record_prediction("c", key="k", predicted=1.0)  # evicts "a"
    assert led.evicted == 1
    # "a" was evicted, so its late actual never joins.
    led.record_actual("a", actual=1.0)
    assert led.stat("k") is None


def test_report_aggregates_multiple_keys() -> None:
    led = SimulationFidelityLedger()
    led.record_prediction("p1", key="cost", predicted=10.0)
    led.record_actual("p1", actual=10.0)
    led.record_prediction("p2", key="capacity", predicted=1.0)
    led.record_actual("p2", actual=2.0)
    report = led.report()
    assert set(report) == {"cost", "capacity"}


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        SimulationFidelityLedger(tolerance=0.0)
    with pytest.raises(ValueError, match="max_pending"):
        SimulationFidelityLedger(max_pending=0)


def test_non_finite_prediction_does_not_poison_key() -> None:
    """A NaN / inf sample must be dropped, not recorded into the stats."""
    led = SimulationFidelityLedger()
    led.record_prediction("bad", key="cost.resize", predicted=float("nan"))
    led.record_actual("bad", actual=100.0)
    # Nothing joined -> key has no stat, so a later healthy sample is clean.
    assert led.stat("cost.resize") is None
    led.record_prediction("good", key="cost.resize", predicted=100.0)
    led.record_actual("good", actual=100.0)
    stat = led.stat("cost.resize")
    assert stat is not None
    assert stat.samples == 1
    assert stat.mape == 0.0


def test_non_finite_actual_is_dropped() -> None:
    led = SimulationFidelityLedger()
    led.record_prediction("p", key="k", predicted=100.0)
    led.record_actual("p", actual=float("inf"))
    # The inf actual is dropped; the prediction stays pending, no stat.
    assert led.stat("k") is None
