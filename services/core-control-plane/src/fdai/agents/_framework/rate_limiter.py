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

The limiter is a deterministic fixed dual-window counter:

- one 60-second window capped at ``per_minute``;
- one 3600-second window capped at ``per_hour``.

The clock is injected (``now``) so tests are deterministic - no reliance on
wall-clock or ``sleep``. ``allow()`` is the only decision surface: it resets
an elapsed window, then admits (and counts) the call when both windows have
budget, or rejects without counting when either is exhausted.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fdai.agents._framework.base import RateLimits

_MINUTE_SECONDS = 60.0
_HOUR_SECONDS = 3600.0


class RateLimiter:
    """Deterministic per-minute + per-hour proposal budget.

    Not thread-safe by design: the pantheon runs one agent coroutine at a
    time on the event loop, so a single-threaded counter is sufficient and
    avoids lock overhead on the emission path.
    """

    __slots__ = (
        "_per_minute",
        "_per_hour",
        "_now",
        "_minute_start",
        "_minute_count",
        "_hour_start",
        "_hour_count",
    )

    def __init__(
        self,
        *,
        per_minute: int,
        per_hour: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute < 1:
            raise ValueError("per_minute MUST be >= 1")
        if per_hour < 1:
            raise ValueError("per_hour MUST be >= 1")
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._now = now
        self._minute_start: float | None = None
        self._minute_count = 0
        self._hour_start: float | None = None
        self._hour_count = 0

    @classmethod
    def from_limits(
        cls, limits: RateLimits, *, now: Callable[[], float] = time.monotonic
    ) -> RateLimiter:
        """Build a limiter from a declared :class:`RateLimits`."""
        return cls(per_minute=limits.per_minute, per_hour=limits.per_hour, now=now)

    def allow(self) -> bool:
        """Admit one proposal against the budget.

        Returns ``True`` and counts the call when both windows have budget;
        returns ``False`` without counting when either window is exhausted
        (so a rejected call does not consume budget it did not get).
        """
        t = self._now()
        if self._minute_start is None or t - self._minute_start >= _MINUTE_SECONDS:
            self._minute_start = t
            self._minute_count = 0
        if self._hour_start is None or t - self._hour_start >= _HOUR_SECONDS:
            self._hour_start = t
            self._hour_count = 0
        if self._minute_count >= self._per_minute or self._hour_count >= self._per_hour:
            return False
        self._minute_count += 1
        self._hour_count += 1
        return True


__all__ = ["RateLimiter"]
