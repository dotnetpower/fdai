"""Resilience primitives (CSP-neutral, I/O-free)."""

from __future__ import annotations

from fdai.shared.resilience.backpressure import (
    Backpressure,
    BackpressureConfig,
    LoadShedError,
)
from fdai.shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
)
from fdai.shared.resilience.degradation import DegradationController, SystemMode
from fdai.shared.resilience.kill_switch import (
    KILL_SWITCH_STATE_KEY,
    InMemoryKillSwitch,
    KillSwitch,
    StateStoreKillSwitch,
)

__all__ = [
    "Backpressure",
    "BackpressureConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitOpenError",
    "CircuitState",
    "DegradationController",
    "KILL_SWITCH_STATE_KEY",
    "InMemoryKillSwitch",
    "KillSwitch",
    "LoadShedError",
    "StateStoreKillSwitch",
    "SystemMode",
]
