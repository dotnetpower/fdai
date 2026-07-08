"""Deterministic tests for the CircuitBreaker (injectable clock)."""

from __future__ import annotations

import pytest

from fdai.shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreakerConfig(failure_threshold=0)
    with pytest.raises(ValueError, match="reset_timeout_s"):
        CircuitBreakerConfig(reset_timeout_s=0)
    with pytest.raises(ValueError, match="half_open_max_calls"):
        CircuitBreakerConfig(half_open_max_calls=0)


def test_trips_open_after_consecutive_failures() -> None:
    cb = CircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=3, reset_timeout_s=10),
        clock=_Clock(),
    )
    assert cb.state is CircuitState.CLOSED
    for _ in range(3):
        cb.on_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow() is False


def test_success_resets_failure_run() -> None:
    cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=3))
    cb.on_failure()
    cb.on_failure()
    cb.on_success()  # resets the run
    cb.on_failure()
    assert cb.state is CircuitState.CLOSED  # only 1 failure since reset


def test_half_open_after_cooldown_then_closes_on_success() -> None:
    clock = _Clock()
    cb = CircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=2, reset_timeout_s=10),
        clock=clock,
    )
    cb.on_failure()
    cb.on_failure()
    assert cb.state is CircuitState.OPEN

    clock.advance(10)  # cooldown elapsed
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allow() is True  # first probe reserved
    assert cb.allow() is False  # half_open_max_calls=1 exhausted
    cb.on_success()
    assert cb.state is CircuitState.CLOSED


def test_half_open_probe_failure_reopens() -> None:
    clock = _Clock()
    cb = CircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=5),
        clock=clock,
    )
    cb.on_failure()
    assert cb.state is CircuitState.OPEN
    clock.advance(5)
    assert cb.state is CircuitState.HALF_OPEN
    cb.on_failure()  # probe failed
    assert cb.state is CircuitState.OPEN
    # cooldown restarted from the new opened_at.
    clock.advance(4)
    assert cb.state is CircuitState.OPEN
    clock.advance(1)
    assert cb.state is CircuitState.HALF_OPEN


async def test_call_returns_value_on_success() -> None:
    cb = CircuitBreaker()

    async def _ok() -> int:
        return 7

    assert await cb.call(_ok) == 7


async def test_call_records_failure_and_fails_fast_when_open() -> None:
    cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=100))

    async def _boom() -> int:
        raise RuntimeError("downstream down")

    with pytest.raises(RuntimeError, match="downstream down"):
        await cb.call(_boom)
    assert cb.state is CircuitState.OPEN

    async def _ok() -> int:
        return 1

    # Circuit is open -> fail fast without calling _ok.
    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)


def test_snapshot_exposes_state() -> None:
    cb = CircuitBreaker(name="github")
    snap = cb.snapshot()
    assert snap["name"] == "github"
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 0
