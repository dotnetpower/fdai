"""Per-agent proposal rate limiter.

Each pantheon agent declares ``rate_limits`` (``agent-pantheon.md`` 7.9:
default ``20 proposals/minute`` and ``100 proposals/hour``). Proposals are
an agent's *discretionary* emissions - rule candidates, chaos experiments,
domain advisories - as opposed to pipeline-critical messages (verdicts,
action runs, approvals, audit entries) which are never rate limited.

A malfunctioning or compromised agent could flood the bus with proposals;
this limiter bounds the burst so downstream consumers (Mimir's
``CandidateGuard``, Odin's arbitration) are protected upstream, in addition
to their own defenses.

The limiter is a deterministic sliding dual-window counter:

- the previous 60 seconds capped at ``per_minute``;
- the previous 3600 seconds capped at ``per_hour``.

The clock is injected (``now``) so tests are deterministic - no reliance on
wall-clock or ``sleep``. ``allow()`` is the only decision surface: it evicts
expired timestamps, then admits (and counts) the call when both windows have
budget, or rejects without counting when either is exhausted. This avoids the
2x burst that a fixed window admits at a boundary.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from fdai.agents._framework.base import RateLimits
from fdai.shared.providers.state_store import StateStore

_MINUTE_SECONDS = 60.0
_HOUR_SECONDS = 3600.0
_STATE_PREFIX = "pantheon/proposal-rate-limit"


class RateLimiter:
    """Deterministic sliding per-minute + per-hour proposal budget.

    Not thread-safe by design: the pantheon runs one agent coroutine at a
    time on the event loop, so a single-threaded counter is sufficient and
    avoids lock overhead on the emission path.
    """

    __slots__ = (
        "_per_minute",
        "_per_hour",
        "_now",
        "_minute_events",
        "_hour_events",
        "_state_store",
        "_state_key",
    )

    def __init__(
        self,
        *,
        per_minute: int,
        per_hour: int,
        now: Callable[[], float] = time.monotonic,
        state_store: StateStore | None = None,
        scope: str = "default",
    ) -> None:
        if per_minute < 1:
            raise ValueError("per_minute MUST be >= 1")
        if per_hour < 1:
            raise ValueError("per_hour MUST be >= 1")
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._now = now
        self._minute_events: deque[float] = deque()
        self._hour_events: deque[float] = deque()
        self._state_store = state_store
        self._state_key = f"{_STATE_PREFIX}/{scope}"
        self._load_durable_windows()

    @classmethod
    def from_limits(
        cls,
        limits: RateLimits,
        *,
        now: Callable[[], float] = time.monotonic,
        state_store: StateStore | None = None,
        scope: str = "default",
    ) -> RateLimiter:
        """Build a limiter from a declared :class:`RateLimits`."""
        return cls(
            per_minute=limits.per_minute,
            per_hour=limits.per_hour,
            now=now,
            state_store=state_store,
            scope=scope,
        )

    def allow(self) -> bool:
        """Admit one proposal against the budget.

        Returns ``True`` and counts the call when both windows have budget;
        returns ``False`` without counting when either window is exhausted
        (so a rejected call does not consume budget it did not get).
        """
        t = self._now()
        self._load_durable_windows()
        _evict_expired(self._minute_events, t - _MINUTE_SECONDS)
        _evict_expired(self._hour_events, t - _HOUR_SECONDS)
        if len(self._minute_events) >= self._per_minute or len(self._hour_events) >= self._per_hour:
            self._save_durable_windows()
            return False
        self._minute_events.append(t)
        self._hour_events.append(t)
        self._save_durable_windows()
        return True

    def _load_durable_windows(self) -> None:
        record = _read_sync_state(self._state_store, self._state_key)
        if record is None:
            return
        minute_events = record.get("minute_events")
        hour_events = record.get("hour_events")
        if not isinstance(minute_events, list) or not isinstance(hour_events, list):
            raise RuntimeError("durable proposal rate-limit window is malformed")
        try:
            self._minute_events = deque(float(item) for item in minute_events)
            self._hour_events = deque(float(item) for item in hour_events)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("durable proposal rate-limit window is malformed") from exc

    def _save_durable_windows(self) -> None:
        if self._state_store is None:
            return
        _write_sync_state(
            self._state_store,
            self._state_key,
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "minute_events": list(self._minute_events),
                "hour_events": list(self._hour_events),
            },
        )


def _read_sync_state(store: StateStore | None, key: str) -> dict[str, Any] | None:
    if store is None:
        return None
    state = getattr(store, "_state", None)
    lock = getattr(store, "_lock", None)
    if isinstance(state, dict) and lock is not None:
        with lock:
            value = state.get(key)
            return deepcopy(dict(value)) if isinstance(value, dict) else None
    raise RuntimeError("proposal rate limiter requires a synchronously readable durable store")


def _write_sync_state(store: StateStore, key: str, value: dict[str, Any]) -> None:
    state = getattr(store, "_state", None)
    lock = getattr(store, "_lock", None)
    write_locked = getattr(store, "_write_locked", None)
    if isinstance(state, dict) and lock is not None and callable(write_locked):
        with lock:
            prior = state.get(key)
            revision = int(prior.get("revision", 0)) + 1 if isinstance(prior, dict) else 1
            stored = dict(value)
            stored["revision"] = revision
            write_locked(key, stored)
        return
    raise RuntimeError("proposal rate limiter requires a synchronously writable durable store")


def _evict_expired(events: deque[float], cutoff: float) -> None:
    while events and events[0] <= cutoff:
        events.popleft()


__all__ = ["RateLimiter"]
