from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.runtime.rule_activation_transport import rule_activation_source_time


def test_recorded_time_is_parsed_and_absent_time_uses_now() -> None:
    assert rule_activation_source_time("2026-10-07T01:00:00+00:00") == datetime(
        2026, 10, 7, 1, tzinfo=UTC
    )
    assert rule_activation_source_time("").tzinfo is not None


@pytest.mark.parametrize(
    ("value", "match"),
    [("not-a-time", "invalid"), ("2026-10-07T01:00:00", "timezone-aware")],
)
def test_invalid_or_naive_time_fails_startup(value: str, match: str) -> None:
    with pytest.raises(RuntimeError, match=match):
        rule_activation_source_time(value)
