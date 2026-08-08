"""Circuit breaker - downstream failure isolation.

The pantheon bridge self-heals a crashed consumer by restarting it, but
nothing today stops the control plane from hammering a *failing*
downstream (Azure ARM, GitHub, Postgres, Kafka): repeated calls into a
dead dependency turn into a retry storm that both wastes the dependency's
recovery budget and blocks the event loop on timeouts. A circuit breaker
is the missing primitive: after a run of failures it trips OPEN and fails
fast (no downstream call at all) until a cooldown elapses, then probes
with a single HALF_OPEN call before closing again.

This module is a pure, I/O-free state machine with an injectable clock so
the transitions are deterministically testable. A composition root wraps
a provider adapter's outbound call with :meth:`CircuitBreaker.call` (or
guards it with :meth:`allow` / :meth:`on_success` / :meth:`on_failure`);
core code never imports a concrete adapter, so the breaker stays
CSP-neutral.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

_T = TypeVar("_T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    """Healthy - calls pass through."""

    OPEN = "open"
    """Tripped - calls fail fast without touching the downstream."""

    HALF_OPEN = "half_open"
    """Cooldown elapsed - a limited number of probe calls are allowed."""


class CircuitOpenError(RuntimeError):
    """Raised by :meth:`CircuitBreaker.call` when the circuit is OPEN."""


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    failure_threshold: int = 5
    """Consecutive failures (in CLOSED) that trip the circuit OPEN."""

    reset_timeout_s: float = 30.0
    """Cooldown after opening before a HALF_OPEN probe is allowed."""

    half_open_max_calls: int = 1
    """Probe calls permitted in HALF_OPEN before it must resolve."""

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold MUST be >= 1")
        if self.reset_timeout_s <= 0:
            raise ValueError("reset_timeout_s MUST be > 0")
        if self.half_open_max_calls < 1:
            raise ValueError("half_open_max_calls MUST be >= 1")


class CircuitBreaker:
    """Deterministic circuit breaker with an injectable monotonic clock."""

    def __init__(
        self,
        *,
        config: CircuitBreakerConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        name: str = "circuit",
    ) -> None:
        self._config = config or CircuitBreakerConfig()
        self._clock = clock
        self._name = name
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._half_open_since = 0.0

    @property
    def state(self) -> CircuitState:
        self._maybe_half_open()
        self._maybe_reopen_stuck_probe()
        return self._state

    def _maybe_half_open(self) -> None:
        if (
            self._state is CircuitState.OPEN
            and self._clock() - self._opened_at >= self._config.reset_timeout_s
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            self._half_open_since = self._clock()

    def _maybe_reopen_stuck_probe(self) -> None:
        """Re-open if a reserved HALF_OPEN probe never resolved.

        A probe reserved via :meth:`allow` that is never followed by
        ``on_success``/``on_failure`` (a hung or lost downstream call)
        would otherwise wedge the breaker HALF_OPEN forever, refusing all
        traffic. After another ``reset_timeout_s`` with an outstanding
        probe, re-trip so the cooldown restarts and a fresh probe is
        eventually allowed.
        """
        if (
            self._state is CircuitState.HALF_OPEN
            and self._half_open_calls > 0
            and self._clock() - self._half_open_since >= self._config.reset_timeout_s
        ):
            self._trip()

    def allow(self) -> bool:
        """Return True if a call may proceed (and reserve a probe slot)."""
        self._maybe_half_open()
        self._maybe_reopen_stuck_probe()
        if self._state is CircuitState.OPEN:
            return False
        if self._state is CircuitState.HALF_OPEN:
            if self._half_open_calls >= self._config.half_open_max_calls:
                return False
            if self._half_open_calls == 0:
                self._half_open_since = self._clock()
            self._half_open_calls += 1
        return True

    def _release_probe(self) -> None:
        """Free a reserved HALF_OPEN probe slot without scoring it.

        Used when a probe call is cancelled (not a downstream failure):
        the reservation is returned so a later probe can retry, and the
        breaker is neither closed nor re-opened by the cancellation.
        """
        if self._state is CircuitState.HALF_OPEN and self._half_open_calls > 0:
            self._half_open_calls -= 1

    def on_success(self) -> None:
        self._consecutive_failures = 0
        if self._state is CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED

    def on_failure(self) -> None:
        self._consecutive_failures += 1
        if self._state is CircuitState.HALF_OPEN:
            # A probe failed - re-open and restart the cooldown.
            self._trip()
        elif self._consecutive_failures >= self._config.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._half_open_calls = 0

    async def call(self, fn: Callable[..., Awaitable[_T]], *args: object, **kwargs: object) -> _T:
        """Guard an async call; raise :class:`CircuitOpenError` when OPEN."""
        if not self.allow():
            raise CircuitOpenError(f"{self._name} circuit is open")
        try:
            result = await fn(*args, **kwargs)
        except asyncio.CancelledError:
            # Cancellation is not a downstream failure: release the probe
            # reservation so the breaker does not wedge HALF_OPEN, and do
            # not count it against the failure threshold.
            self._release_probe()
            raise
        except Exception:
            self.on_failure()
            raise
        self.on_success()
        return result

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self._name,
            "state": self.state.value,
            "consecutive_failures": self._consecutive_failures,
        }


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitOpenError",
    "CircuitState",
]
