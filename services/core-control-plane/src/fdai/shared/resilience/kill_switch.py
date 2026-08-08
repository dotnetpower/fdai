"""Global kill-switch - operator-triggered emergency halt.

Distinct from the :class:`DegradationController` (automatic, breaker-driven):
the kill-switch is a **deliberate operator action** (RBAC capability
``TRIGGER_KILL_SWITCH``) that halts all auto-execution immediately and drops
every decision path to shadow (security-and-identity.md "Rate Limiting and
Kill-Switch"). It is operable **without the executor identity** - a fork backs
the state in the shared state store so a non-executor principal can flip it and
every replica observes it.

The seam is synchronous and I/O-free so the pure risk-gate can consult it in the
hot path (mirroring :meth:`DegradationController.autonomy_permitted`). A durable,
cluster-wide backing (state-store poll refreshing a cached flag) is a fork
adapter; the in-memory default keeps upstream tests and dev free of external
state.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fdai.shared.providers.state_store import StateStore

KILL_SWITCH_STATE_KEY = "system:kill-switch"


@runtime_checkable
class KillSwitch(Protocol):
    """The global emergency-halt seam consulted by the risk gate."""

    def is_engaged(self) -> bool:
        """True when the emergency halt is active.

        When engaged, the risk gate caps every decision to shadow so no
        action auto-executes (a human path stays open via HIL). False is the
        normal posture - the gate behaves exactly as if no kill-switch were
        wired.
        """
        ...


class InMemoryKillSwitch:
    """Process-local kill-switch (upstream default).

    A fork replaces this with a state-store-backed implementation so the switch
    is durable and cluster-wide (security-and-identity.md: operable without the
    executor identity). In-memory keeps tests and dev free of external state.
    """

    __slots__ = ("_engaged",)

    def __init__(self, *, engaged: bool = False) -> None:
        self._engaged = engaged

    def is_engaged(self) -> bool:
        return self._engaged

    def engage(self) -> None:
        """Activate the halt. Every subsequent decision caps to shadow."""
        self._engaged = True

    def disengage(self) -> None:
        """Clear the halt. Decisions return to the normal ceiling."""
        self._engaged = False


class StateStoreKillSwitch:
    """Cached kill-switch refreshed from the shared state store.

    The synchronous :class:`KillSwitch` read stays I/O-free in the hot path.
    The control loop calls :meth:`refresh` immediately before each authority
    decision. The cache starts engaged, so an action cannot execute before the
    first successful state read.
    """

    __slots__ = ("_engaged", "_store")

    def __init__(self, *, store: StateStore) -> None:
        self._store = store
        self._engaged = True

    def is_engaged(self) -> bool:
        return self._engaged

    async def refresh(self) -> None:
        """Refresh the cached state, rejecting malformed persisted values."""
        state = await self._store.read_state(KILL_SWITCH_STATE_KEY)
        if state is None:
            self._engaged = False
            return
        engaged = state.get("engaged")
        if not isinstance(engaged, bool):
            raise ValueError("kill-switch state engaged MUST be a boolean")
        self._engaged = engaged


__all__ = [
    "KILL_SWITCH_STATE_KEY",
    "InMemoryKillSwitch",
    "KillSwitch",
    "StateStoreKillSwitch",
]
