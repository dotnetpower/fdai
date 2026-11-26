"""OnCallResolver - fail-safe on-call responder resolution.

Covers: no schedule bound -> fallback; live coverage -> responder OIDs; a gap
in coverage -> fallback; a provider outage (OnCallScheduleError) is swallowed
into a fallback (never raises). Uses the real StaticOnCallSchedule plus a tiny
raising fake. Async tests run under asyncio_mode="auto".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.oncall import OnCallResolver
from fdai.shared.providers.oncall_schedule import (
    OnCallSchedule,
    OnCallScheduleError,
    OnCallShift,
    StaticOnCallSchedule,
)

_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _shift(rotation: str = "sre-primary") -> OnCallShift:
    return OnCallShift(
        rotation=rotation,
        primary_oid="oid-primary",
        secondary_oid="oid-secondary",
        start=_NOW - timedelta(hours=1),
        until=_NOW + timedelta(hours=1),
    )


class _RaisingSchedule:
    async def current(self, *, rotation: str, at: datetime) -> OnCallShift | None:
        raise OnCallScheduleError("roster API unreachable")


async def test_no_schedule_bound_falls_back() -> None:
    result = await OnCallResolver().resolve(rotation="sre-primary", at=_NOW)
    assert result.from_schedule is False
    assert result.fallback_reason == "no_schedule_bound"
    assert result.has_responder is False


async def test_live_coverage_returns_responder_oids() -> None:
    resolver = OnCallResolver(StaticOnCallSchedule([_shift()]))
    result = await resolver.resolve(rotation="sre-primary", at=_NOW)
    assert result.from_schedule is True
    assert result.fallback_reason is None
    assert result.primary_oid == "oid-primary"
    assert result.secondary_oid == "oid-secondary"
    assert result.has_responder is True


async def test_gap_in_coverage_falls_back() -> None:
    resolver = OnCallResolver(StaticOnCallSchedule([_shift()]))
    result = await resolver.resolve(rotation="sre-primary", at=_NOW + timedelta(hours=5))
    assert result.from_schedule is False
    assert result.fallback_reason == "no_coverage"
    assert result.has_responder is False


async def test_unknown_rotation_falls_back() -> None:
    resolver = OnCallResolver(StaticOnCallSchedule([_shift()]))
    result = await resolver.resolve(rotation="does-not-exist", at=_NOW)
    assert result.from_schedule is False
    assert result.fallback_reason == "no_coverage"


async def test_provider_outage_is_swallowed_into_fallback() -> None:
    resolver = OnCallResolver(_RaisingSchedule())
    result = await resolver.resolve(rotation="sre-primary", at=_NOW)
    assert result.from_schedule is False
    assert result.fallback_reason == "lookup_failed:OnCallScheduleError"
    assert result.has_responder is False


def test_resolver_accepts_the_protocol_type() -> None:
    # StaticOnCallSchedule satisfies the OnCallSchedule Protocol.
    assert isinstance(StaticOnCallSchedule([]), OnCallSchedule)
