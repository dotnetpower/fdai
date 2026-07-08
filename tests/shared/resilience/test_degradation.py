"""Tests for the DegradationController system autonomy ceiling."""

from __future__ import annotations

import pytest

from fdai.shared.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from fdai.shared.resilience.degradation import DegradationController, SystemMode


def _tripped() -> CircuitBreaker:
    cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=300))
    cb.on_failure()  # trips OPEN and stays open (long cooldown)
    return cb


def test_normal_when_all_breakers_closed() -> None:
    dc = DegradationController(breakers={"a": CircuitBreaker(), "b": CircuitBreaker()})
    assert dc.mode is SystemMode.NORMAL
    assert dc.autonomy_permitted() is True
    assert dc.open_circuits() == []


def test_degraded_when_a_breaker_opens() -> None:
    dc = DegradationController(breakers={"a": _tripped(), "b": CircuitBreaker()})
    assert dc.mode is SystemMode.DEGRADED
    assert dc.autonomy_permitted() is False
    assert dc.open_circuits() == ["a"]


def test_open_threshold_requires_enough_open_circuits() -> None:
    dc = DegradationController(
        breakers={"a": _tripped(), "b": CircuitBreaker()}, open_threshold=2
    )
    assert dc.mode is SystemMode.NORMAL  # only 1 open, threshold is 2


def test_threshold_validation() -> None:
    with pytest.raises(ValueError, match="open_threshold"):
        DegradationController(breakers={}, open_threshold=0)


def test_snapshot_reports_open_circuits() -> None:
    dc = DegradationController(breakers={"a": _tripped()})
    snap = dc.snapshot()
    assert snap["mode"] == "degraded"
    assert snap["open_circuits"] == ["a"]
