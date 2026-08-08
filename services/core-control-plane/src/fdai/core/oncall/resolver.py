"""On-call responder resolution - the fail-safe wrapper every HIL / paging
consumer shares.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md`` section 3.5.

The :class:`~fdai.shared.providers.oncall_schedule.OnCallSchedule` provider
answers "who is on shift right now", but its docstring puts a contract on every
caller: catch :class:`OnCallScheduleError` and fall back to the standard
role-based routing so a schedule-provider outage never drops a HIL request
(fail-closed on coverage, fail-safe on notification). Re-implementing that
try / except in each consumer (the HIL coordinator, the break-glass pager, a
future alert router) invites one of them getting it wrong.

:class:`OnCallResolver` centralizes it. It never raises and never drops: a
missing schedule binding, a gap in coverage, or a lookup failure all return a
resolution with ``from_schedule=False`` so the caller applies its own
role-based default. When coverage exists, it returns the primary and secondary
responder OIDs the caller can address directly.

CSP-neutral: imports only the provider Protocol and the standard library, so it
stays under the ``core/`` import rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from fdai.shared.providers.oncall_schedule import OnCallSchedule, OnCallScheduleError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OnCallResolution:
    """The resolved (or fallen-back) on-call responder for a rotation."""

    rotation: str
    primary_oid: str | None
    secondary_oid: str | None
    from_schedule: bool
    fallback_reason: str | None
    """``None`` when ``from_schedule`` is True; otherwise a machine-readable
    reason (``no_schedule_bound`` / ``no_coverage`` / ``lookup_failed:<type>``)
    the caller records in audit before applying role-based routing."""

    @property
    def has_responder(self) -> bool:
        """True when a concrete on-call primary was resolved from the schedule."""
        return self.primary_oid is not None


class OnCallResolver:
    """Fail-safe resolution of the current on-call responder for a rotation."""

    __slots__ = ("_schedule",)

    def __init__(self, schedule: OnCallSchedule | None = None) -> None:
        self._schedule = schedule

    async def resolve(self, *, rotation: str, at: datetime) -> OnCallResolution:
        """Return the responder covering ``at`` in ``rotation``, or a fallback.

        Never raises. When no schedule is bound, coverage is absent, or the
        lookup fails, the result carries ``from_schedule=False`` and a
        ``fallback_reason`` so the caller routes by role instead.
        """
        if self._schedule is None:
            return OnCallResolution(
                rotation=rotation,
                primary_oid=None,
                secondary_oid=None,
                from_schedule=False,
                fallback_reason="no_schedule_bound",
            )
        try:
            shift = await self._schedule.current(rotation=rotation, at=at)
        except OnCallScheduleError as exc:
            _LOGGER.warning(
                "oncall_lookup_failed",
                extra={"rotation": rotation, "error": type(exc).__name__},
            )
            return OnCallResolution(
                rotation=rotation,
                primary_oid=None,
                secondary_oid=None,
                from_schedule=False,
                fallback_reason=f"lookup_failed:{type(exc).__name__}",
            )
        if shift is None:
            return OnCallResolution(
                rotation=rotation,
                primary_oid=None,
                secondary_oid=None,
                from_schedule=False,
                fallback_reason="no_coverage",
            )
        return OnCallResolution(
            rotation=rotation,
            primary_oid=shift.primary_oid,
            secondary_oid=shift.secondary_oid,
            from_schedule=True,
            fallback_reason=None,
        )


__all__ = ["OnCallResolution", "OnCallResolver"]
