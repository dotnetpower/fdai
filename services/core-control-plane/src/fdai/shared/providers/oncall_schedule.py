"""On-call schedule - who is on-shift right now.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.5``.

The HIL / paging surface today (``HilChannel``, ``BreakGlassPager``)
routes by role only - it does not know **who is on shift right now**.
This Protocol is the seam that fixes that gap. Upstream ships a static
in-memory implementation (:class:`StaticOnCallSchedule`) so the seam
exists without pulling any external dependency; fork adapters
(PagerDuty, OpsGenie, Opsgenie-alike) live under
``delivery/<vendor>/`` and are bound at the composition root.

Async by contract - a real schedule lookup is an HTTP round-trip to
the vendor's roster API.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class OnCallShift:
    """One shift interval.

    ``primary_oid`` is the Entra OID (immutable identifier) of the
    primary responder; ``secondary_oid`` is the escalation target if
    the primary does not ack within the vendor-side timeout. ``until``
    is the exclusive end of the shift in UTC.
    """

    rotation: str
    primary_oid: str
    secondary_oid: str | None
    start: datetime
    until: datetime


class OnCallScheduleError(RuntimeError):
    """Raised on any unrecoverable schedule-lookup failure.

    Callers MUST catch this and fall back to the standard
    role-based routing (`HilChannel` semantics) so an outage of the
    schedule provider never drops a HIL request - fail-closed on
    coverage, fail-safe on notification.
    """


@runtime_checkable
class OnCallSchedule(Protocol):
    """Look up the on-call shift active at ``at`` for a rotation."""

    async def current(self, *, rotation: str, at: datetime) -> OnCallShift | None:
        """Return the shift that covers ``at`` in ``rotation``.

        ``None`` means the rotation has no coverage at ``at`` - the
        caller MUST fall back to the role-based routing rather than
        drop the request.
        """
        ...


class StaticOnCallSchedule:
    """In-memory schedule for tests and small deployments.

    Shifts are held as a per-rotation list sorted by start time; a
    lookup runs binary search for O(log n) resolution. Overlapping
    shifts within one rotation are rejected at construction: the
    schedule MUST be unambiguous.
    """

    def __init__(self, shifts: Sequence[OnCallShift]) -> None:
        by_rotation: dict[str, list[OnCallShift]] = {}
        for shift in shifts:
            if shift.until <= shift.start:
                raise ValueError(f"shift for rotation {shift.rotation!r} has non-positive duration")
            by_rotation.setdefault(shift.rotation, []).append(shift)
        # Sort per-rotation and verify non-overlap.
        for rotation, entries in by_rotation.items():
            entries.sort(key=lambda s: s.start)
            for a, b in zip(entries, entries[1:], strict=False):
                if a.until > b.start:
                    raise ValueError(
                        f"rotation {rotation!r} has overlapping shifts around {b.start.isoformat()}"
                    )
        self._by_rotation: dict[str, list[OnCallShift]] = by_rotation

    async def current(self, *, rotation: str, at: datetime) -> OnCallShift | None:
        entries = self._by_rotation.get(rotation, [])
        if not entries:
            return None
        starts = [s.start for s in entries]
        # Rightmost index with start <= at, then verify until > at.
        idx = bisect.bisect_right(starts, at) - 1
        if idx < 0:
            return None
        candidate = entries[idx]
        if candidate.start <= at < candidate.until:
            return candidate
        return None


__all__ = [
    "OnCallSchedule",
    "OnCallScheduleError",
    "OnCallShift",
    "StaticOnCallSchedule",
]
