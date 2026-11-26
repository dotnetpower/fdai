"""Degradation controller - system-level fail-toward-safety.

Individual circuit breakers isolate a *single* failing downstream. This
controller aggregates them into a system-wide autonomy ceiling: when one
or more dependencies are tripped OPEN, the control plane is DEGRADED and
autonomy is capped to shadow - a failing dependency (a broken audit store,
an unreachable substrate) MUST NOT drive an enforce-mode mutation. That
is the "fail toward safety" rule at the system scope, above the per-call
circuit breaker.

Pure and I/O-free: it reads the breakers' current state (which themselves
use an injectable clock) so the mode is deterministically testable. A
composition root registers the breakers guarding each critical dependency
and consults :meth:`autonomy_permitted` before promoting an action to
enforce; ``core`` never imports a concrete adapter, so this stays
CSP-neutral.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.resilience.circuit_breaker import CircuitBreaker, CircuitState


class SystemMode(StrEnum):
    NORMAL = "normal"
    """All critical dependencies healthy - full autonomy permitted."""

    DEGRADED = "degraded"
    """One or more dependencies tripped - autonomy capped to shadow."""


@dataclass(frozen=True, slots=True)
class DegradationController:
    """Aggregate circuit-breaker health into an autonomy ceiling."""

    breakers: Mapping[str, CircuitBreaker]
    open_threshold: int = 1
    """Number of OPEN breakers that flips the system to DEGRADED."""

    def __post_init__(self) -> None:
        if self.open_threshold < 1:
            raise ValueError("open_threshold MUST be >= 1")

    def open_circuits(self) -> list[str]:
        """Names of breakers that are not fully CLOSED (OPEN or HALF_OPEN).

        A HALF_OPEN breaker is still *probing* - recovery is unconfirmed
        until a probe succeeds and it CLOSES. Counting HALF_OPEN as
        degraded keeps the system from resuming enforce-mode autonomy the
        instant a cooldown elapses, before the dependency is proven
        healthy. That is the "fail toward safety" rule at system scope.
        """
        return [
            name
            for name, breaker in self.breakers.items()
            if breaker.state is not CircuitState.CLOSED
        ]

    @property
    def mode(self) -> SystemMode:
        if len(self.open_circuits()) >= self.open_threshold:
            return SystemMode.DEGRADED
        return SystemMode.NORMAL

    def autonomy_permitted(self) -> bool:
        """True when the system is healthy enough to run enforce actions.

        False caps the caller to shadow (fail toward safety) - the pantheon
        runtime and the risk gate consult this before letting an action
        mutate while a critical dependency is down.
        """
        return self.mode is SystemMode.NORMAL

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "open_circuits": self.open_circuits(),
            "open_threshold": self.open_threshold,
        }


__all__ = ["DegradationController", "SystemMode"]
