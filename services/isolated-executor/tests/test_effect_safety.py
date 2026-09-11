"""Focused checks for isolated-Executor effect safety helpers."""

from datetime import UTC, datetime, timedelta, tzinfo

import pytest
from fdai_executor_service.effect_safety import deadline_expired


class _UnresolvedTimezone(tzinfo):
    def utcoffset(self, _dt: datetime | None) -> None:
        return None

    def dst(self, _dt: datetime | None) -> None:
        return None


def test_deadline_expires_at_the_exact_boundary() -> None:
    deadline_at = datetime(2026, 9, 11, tzinfo=UTC)

    assert deadline_expired(deadline_at - timedelta(microseconds=1), deadline_at) is False
    assert deadline_expired(deadline_at, deadline_at) is True


@pytest.mark.parametrize(
    ("now", "deadline_at"),
    [
        (datetime(2026, 9, 11), datetime(2026, 9, 12, tzinfo=UTC)),
        (
            datetime(2026, 9, 11, tzinfo=_UnresolvedTimezone()),
            datetime(2026, 9, 12, tzinfo=UTC),
        ),
    ],
)
def test_deadline_rejects_unresolved_timezones(
    now: datetime,
    deadline_at: datetime,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        deadline_expired(now, deadline_at)
