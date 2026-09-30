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

import asyncio
import time
from collections import deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
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
        "_reservations",
        "_reservation_sequence",
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
        self._reservations: dict[str, float] = {}
        self._reservation_sequence = 0
        if self._state_store is None:
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

    async def reserve(self) -> RateLimitReservation | None:
        """Reserve one proposal slot without consuming it.

        The caller must ``commit`` after the proposal is durably published, or
        ``release`` on publish failure. Durable stores use
        :meth:`StateStore.compare_and_set_state`, so two runtime replicas
        racing for the final slot cannot both reserve it.
        """

        if self._state_store is None:
            return self._reserve_memory()
        return await self._reserve_durable()

    def _reserve_memory(self) -> RateLimitReservation | None:
        t = self._now()
        _evict_expired(self._minute_events, t - _MINUTE_SECONDS)
        _evict_expired(self._hour_events, t - _HOUR_SECONDS)
        active_reservations = sum(
            1 for reserved_at in self._reservations.values() if reserved_at > t - _HOUR_SECONDS
        )
        minute_reservations = sum(
            1 for reserved_at in self._reservations.values() if reserved_at > t - _MINUTE_SECONDS
        )
        if (
            len(self._minute_events) + minute_reservations >= self._per_minute
            or len(self._hour_events) + active_reservations >= self._per_hour
        ):
            return None
        token = self._next_reservation_token(t)
        self._reservations[token] = t
        return RateLimitReservation(self, token, False)

    async def _reserve_durable(self) -> RateLimitReservation | None:
        store = self._durable_store()
        for _attempt in range(16):
            t = self._now()
            record = _normalize_record(await store.read_state(self._state_key))
            minute_events = deque(record["minute_events"])
            hour_events = deque(record["hour_events"])
            reservations = dict(record["reservations"])
            _evict_expired(minute_events, t - _MINUTE_SECONDS)
            _evict_expired(hour_events, t - _HOUR_SECONDS)
            reservations = {
                token: reserved_at
                for token, reserved_at in reservations.items()
                if reserved_at > t - _HOUR_SECONDS
            }
            minute_reservations = sum(
                1 for reserved_at in reservations.values() if reserved_at > t - _MINUTE_SECONDS
            )
            if (
                len(minute_events) + minute_reservations >= self._per_minute
                or len(hour_events) + len(reservations) >= self._per_hour
            ):
                await self._store_record(
                    minute_events=minute_events,
                    hour_events=hour_events,
                    reservations=reservations,
                    expected_revision=int(record["revision"]),
                )
                return None
            token = self._next_reservation_token(t)
            reservations[token] = t
            stored = await self._store_record(
                minute_events=minute_events,
                hour_events=hour_events,
                reservations=reservations,
                expected_revision=int(record["revision"]),
            )
            if stored:
                return RateLimitReservation(self, token, True)
            await asyncio.sleep(0)
        raise RuntimeError("proposal rate limiter CAS retry limit exceeded")

    async def _commit_reservation(self, token: str, *, durable: bool) -> None:
        if not durable:
            reserved_at = self._reservations.pop(token, None)
            if reserved_at is None:
                return
            self._minute_events.append(reserved_at)
            self._hour_events.append(reserved_at)
            return
        store = self._durable_store()
        for _attempt in range(16):
            record = _normalize_record(await store.read_state(self._state_key))
            reservations = dict(record["reservations"])
            reserved_at = reservations.pop(token, None)
            if reserved_at is None:
                return
            minute_events = deque(record["minute_events"])
            hour_events = deque(record["hour_events"])
            minute_events.append(reserved_at)
            hour_events.append(reserved_at)
            if await self._store_record(
                minute_events=minute_events,
                hour_events=hour_events,
                reservations=reservations,
                expected_revision=int(record["revision"]),
            ):
                return
            await asyncio.sleep(0)
        raise RuntimeError("proposal rate limiter commit CAS retry limit exceeded")

    async def _release_reservation(self, token: str, *, durable: bool) -> None:
        if not durable:
            self._reservations.pop(token, None)
            return
        store = self._durable_store()
        for _attempt in range(16):
            record = _normalize_record(await store.read_state(self._state_key))
            reservations = dict(record["reservations"])
            if token not in reservations:
                return
            reservations.pop(token, None)
            if await self._store_record(
                minute_events=deque(record["minute_events"]),
                hour_events=deque(record["hour_events"]),
                reservations=reservations,
                expected_revision=int(record["revision"]),
            ):
                return
            await asyncio.sleep(0)
        raise RuntimeError("proposal rate limiter release CAS retry limit exceeded")

    async def _store_record(
        self,
        *,
        minute_events: deque[float],
        hour_events: deque[float],
        reservations: dict[str, float],
        expected_revision: int,
    ) -> bool:
        store = self._durable_store()
        value = {
            "schema_version": "1.0.0",
            "revision": expected_revision + 1,
            "minute_events": list(minute_events),
            "hour_events": list(hour_events),
            "reservations": reservations,
        }
        if expected_revision == 0:
            return await store.write_state_if_absent(self._state_key, value)
        return await store.compare_and_set_state(
            self._state_key,
            value,
            expected_revision=expected_revision,
        )

    def _next_reservation_token(self, timestamp: float) -> str:
        self._reservation_sequence += 1
        return f"{self._state_key}/{id(self):x}/{self._reservation_sequence}/{timestamp:.9f}"

    def _durable_store(self) -> StateStore:
        if self._state_store is None:
            raise RuntimeError("proposal rate limiter durable store is unavailable")
        return self._state_store

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
                "reservations": {},
            },
        )


@dataclass(slots=True)
class RateLimitReservation:
    """One tentative proposal budget reservation."""

    _limiter: RateLimiter
    _token: str
    _durable: bool
    _closed: bool = False

    async def commit(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._limiter._commit_reservation(self._token, durable=self._durable)

    async def release(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._limiter._release_reservation(self._token, durable=self._durable)


def _normalize_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {"revision": 0, "minute_events": [], "hour_events": [], "reservations": {}}
    minute_events = record.get("minute_events")
    hour_events = record.get("hour_events")
    reservations = record.get("reservations", {})
    if (
        not isinstance(minute_events, list)
        or not isinstance(hour_events, list)
        or not isinstance(reservations, dict)
    ):
        raise RuntimeError("durable proposal rate-limit window is malformed")
    try:
        normalized_reservations = {
            str(token): float(value) for token, value in reservations.items()
        }
        return {
            "revision": int(record.get("revision", 0)),
            "minute_events": [float(item) for item in minute_events],
            "hour_events": [float(item) for item in hour_events],
            "reservations": normalized_reservations,
        }
    except (TypeError, ValueError) as exc:
        raise RuntimeError("durable proposal rate-limit window is malformed") from exc


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


__all__ = ["RateLimiter", "RateLimitReservation"]
