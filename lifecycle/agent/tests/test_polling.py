from __future__ import annotations

from unittest.mock import Mock

import pytest

from fdai_lifecycle_agent.polling import PollLimits, poll_bounded


def test_count_and_interval_are_exact() -> None:
    poll = Mock(return_value=0)
    sleeps: list[float] = []
    assert poll_bounded(poll, PollLimits(3, 2, 30), monotonic=lambda: 0, sleep=sleeps.append) == 0
    assert poll.call_count == 3
    assert sleeps == [2, 2]


def test_failure_ends_session_without_retry_or_sleep() -> None:
    poll = Mock(return_value=1)
    sleep = Mock()
    assert poll_bounded(poll, PollLimits(), monotonic=lambda: 0, sleep=sleep) == 1
    assert poll.call_count == 1
    sleep.assert_not_called()


def test_deadline_refuses_another_poll_or_sleep() -> None:
    clock = iter([0.0, 0.0, 9.0, 9.0])
    poll = Mock(return_value=0)
    sleep = Mock()
    assert poll_bounded(poll, PollLimits(2, 2, 10), monotonic=lambda: next(clock), sleep=sleep) == 1
    assert poll.call_count == 1
    sleep.assert_not_called()


def test_apply_finishes_recovery_but_no_new_poll_starts_after_deadline() -> None:
    clock = iter([0.0, 0.0, 11.0])
    poll = Mock(return_value=0)
    assert poll_bounded(poll, PollLimits(2, 1, 10), monotonic=lambda: next(clock)) == 1
    assert poll.call_count == 1


@pytest.mark.parametrize(
    "limits",
    [
        (0, 1, 10),
        (10001, 1, 10),
        (1, 0, 10),
        (1, -1, 10),
        (1, float("nan"), 10),
        (1, float("inf"), 10),
        (1, 1, 0),
        (1, 1, float("nan")),
        (1, 1, float("inf")),
    ],
)
def test_invalid_limits_are_rejected(limits: tuple[int, float, float]) -> None:
    with pytest.raises(ValueError):
        PollLimits(*limits)
