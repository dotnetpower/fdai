"""Deterministic tests for the per-agent proposal rate limiter.

The limiter is the enforcement mechanism behind ``agent-pantheon.md`` 7.9
(``20 proposals/minute``, ``100 proposals/hour`` defaults). A controllable
clock keeps every assertion deterministic - no wall-clock, no sleep.
"""

from __future__ import annotations

import pytest
from fdai.agents._framework.base import RateLimits
from fdai.agents._framework.rate_limiter import RateLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_admits_up_to_the_per_minute_cap_then_rejects() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(per_minute=3, per_hour=100, now=clock.now)
    assert [limiter.allow() for _ in range(4)] == [True, True, True, False]


def test_minute_window_refills_after_60_seconds() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(per_minute=2, per_hour=100, now=clock.now)
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False  # minute budget exhausted
    clock.advance(60.0)
    assert limiter.allow() is True  # window reset


def test_hour_cap_binds_even_when_minute_has_budget() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(per_minute=100, per_hour=3, now=clock.now)
    # Spend the hour budget one per minute so the minute window never caps.
    for _ in range(3):
        assert limiter.allow() is True
        clock.advance(60.0)
    # Hour budget exhausted; a fresh minute window does not refill the hour.
    assert limiter.allow() is False
    clock.advance(3600.0)
    assert limiter.allow() is True  # hour window reset


def test_rejected_call_does_not_consume_budget() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(per_minute=1, per_hour=100, now=clock.now)
    assert limiter.allow() is True
    assert limiter.allow() is False
    assert limiter.allow() is False  # still rejected, budget not further drained
    clock.advance(60.0)
    assert limiter.allow() is True  # exactly one slot restored


def test_from_limits_uses_declared_caps() -> None:
    limiter = RateLimiter.from_limits(RateLimits(per_minute=1, per_hour=1))
    assert limiter.allow() is True
    assert limiter.allow() is False


@pytest.mark.parametrize(
    ("per_minute", "per_hour"),
    [(0, 100), (20, 0), (-1, 100)],
)
def test_non_positive_caps_are_rejected(per_minute: int, per_hour: int) -> None:
    with pytest.raises(ValueError):
        RateLimiter(per_minute=per_minute, per_hour=per_hour)
