"""Coverage for action-outcome timestamp admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.measurement.outcome_contract import accepted_outcome_timestamp

_RECORDED = datetime(2026, 8, 31, tzinfo=UTC)


@pytest.mark.parametrize(
    "observed",
    (
        _RECORDED,
        _RECORDED.isoformat(),
        _RECORDED.isoformat().replace("+00:00", "Z"),
    ),
)
def test_accepts_aware_datetime_or_rfc3339_string(observed: object) -> None:
    assert accepted_outcome_timestamp(observed, recorded_at=_RECORDED) is not None


@pytest.mark.parametrize(
    ("observed", "recorded"),
    (
        ("not-a-time", _RECORDED),
        (_RECORDED.replace(tzinfo=None), _RECORDED),
        (_RECORDED, _RECORDED.replace(tzinfo=None)),
        (object(), _RECORDED),
        (_RECORDED + timedelta(minutes=5, microseconds=1), _RECORDED),
    ),
)
def test_rejects_invalid_or_excessively_future_timestamp(
    observed: object,
    recorded: object,
) -> None:
    assert accepted_outcome_timestamp(observed, recorded_at=recorded) is None
