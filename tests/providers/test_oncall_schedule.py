"""OnCallSchedule provider - Protocol conformance + shift resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.shared.providers.oncall_schedule import (
    OnCallSchedule,
    OnCallShift,
    StaticOnCallSchedule,
)

T0 = datetime(2026, 7, 7, 9, 0, 0, tzinfo=UTC)


def _shift(rotation: str, start: datetime, hours: int, primary: str) -> OnCallShift:
    return OnCallShift(
        rotation=rotation,
        primary_oid=primary,
        secondary_oid=None,
        start=start,
        until=start + timedelta(hours=hours),
    )


def test_static_schedule_conforms_to_protocol() -> None:
    assert isinstance(StaticOnCallSchedule(shifts=[]), OnCallSchedule)


async def test_current_returns_the_covering_shift() -> None:
    schedule = StaticOnCallSchedule(
        shifts=[
            _shift("web", T0, hours=8, primary="oid-alice"),
            _shift("web", T0 + timedelta(hours=8), hours=8, primary="oid-bob"),
        ]
    )
    got = await schedule.current(rotation="web", at=T0 + timedelta(hours=1))
    assert got is not None
    assert got.primary_oid == "oid-alice"

    got2 = await schedule.current(rotation="web", at=T0 + timedelta(hours=10))
    assert got2 is not None
    assert got2.primary_oid == "oid-bob"


async def test_current_returns_none_when_gap_between_shifts() -> None:
    schedule = StaticOnCallSchedule(
        shifts=[
            _shift("web", T0, hours=4, primary="oid-alice"),
            _shift("web", T0 + timedelta(hours=6), hours=4, primary="oid-bob"),
        ]
    )
    # 5 hour mark falls in the gap - no coverage.
    got = await schedule.current(rotation="web", at=T0 + timedelta(hours=5))
    assert got is None


async def test_current_returns_none_for_unknown_rotation() -> None:
    schedule = StaticOnCallSchedule(shifts=[_shift("web", T0, hours=8, primary="oid-alice")])
    got = await schedule.current(rotation="database", at=T0)
    assert got is None


async def test_current_returns_none_before_first_shift() -> None:
    schedule = StaticOnCallSchedule(shifts=[_shift("web", T0, hours=8, primary="oid-alice")])
    got = await schedule.current(rotation="web", at=T0 - timedelta(hours=1))
    assert got is None


async def test_current_is_end_exclusive_at_boundary() -> None:
    """Shift `until` is exclusive - a lookup at exactly `until` yields no coverage.

    This matches how `bisect_right` + `<` half-open ranges compose;
    the guarantee is important for adjacent shifts where the second
    shift's `start` == first shift's `until`.
    """
    schedule = StaticOnCallSchedule(
        shifts=[
            _shift("web", T0, hours=8, primary="oid-alice"),
            _shift("web", T0 + timedelta(hours=8), hours=8, primary="oid-bob"),
        ]
    )
    got = await schedule.current(rotation="web", at=T0 + timedelta(hours=8))
    assert got is not None
    assert got.primary_oid == "oid-bob"


def test_constructor_rejects_zero_or_negative_duration_shift() -> None:
    bad = OnCallShift(
        rotation="web",
        primary_oid="oid-alice",
        secondary_oid=None,
        start=T0,
        until=T0,  # zero-duration
    )
    with pytest.raises(ValueError, match="non-positive duration"):
        StaticOnCallSchedule(shifts=[bad])


def test_constructor_rejects_overlapping_shifts_in_one_rotation() -> None:
    overlapping = [
        _shift("web", T0, hours=8, primary="oid-alice"),
        _shift("web", T0 + timedelta(hours=4), hours=8, primary="oid-bob"),
    ]
    with pytest.raises(ValueError, match="overlapping shifts"):
        StaticOnCallSchedule(shifts=overlapping)
