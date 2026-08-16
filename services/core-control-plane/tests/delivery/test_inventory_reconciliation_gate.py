from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    failure_retry_delay_seconds,
    has_unreconciled_change,
    inventory_reconciliation_due,
)


@pytest.mark.parametrize(
    (
        "age_seconds",
        "in_progress",
        "failure_streak",
        "abandoned_attempt",
        "expected",
    ),
    [
        (None, False, 0, False, True),
        (1_000.0, False, 1, False, True),
        (1_000.0, False, 0, True, True),
        (21_599.0, False, 0, False, False),
        (21_600.0, False, 0, False, True),
        (99_999.0, True, 1, True, False),
    ],
)
def test_reconciliation_due_reduces_durable_attempt_state(
    age_seconds: float | None,
    in_progress: bool,
    failure_streak: int,
    abandoned_attempt: bool,
    expected: bool,
) -> None:
    assert (
        inventory_reconciliation_due(
            age_seconds=age_seconds,
            in_progress=in_progress,
            failure_streak=failure_streak,
            failure_age_seconds=None if failure_streak == 0 else 1_000.0,
            abandoned_attempt=abandoned_attempt,
            interval_seconds=21_600,
        )
        is expected
    )


def test_reconciliation_due_rejects_busy_loop_interval() -> None:
    with pytest.raises(ValueError, match=">= 60"):
        inventory_reconciliation_due(
            age_seconds=None,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=59,
        )


@pytest.mark.parametrize(
    ("age_seconds", "change_demand", "expected"),
    [
        (119.0, True, False),
        (120.0, True, True),
        (21_599.0, True, True),
        (21_599.0, False, False),
    ],
)
def test_observed_change_makes_a_scan_due_above_the_floor(
    age_seconds: float,
    change_demand: bool,
    expected: bool,
) -> None:
    """A change shortens the wait to the floor without removing the floor."""

    assert (
        inventory_reconciliation_due(
            age_seconds=age_seconds,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            change_demand=change_demand,
            change_min_interval_seconds=120,
        )
        is expected
    )


def test_change_demand_never_overrides_an_in_progress_attempt() -> None:
    assert (
        inventory_reconciliation_due(
            age_seconds=100_000.0,
            in_progress=True,
            abandoned_attempt=False,
            interval_seconds=21_600,
            change_demand=True,
            change_min_interval_seconds=120,
        )
        is False
    )


def test_reconciliation_due_rejects_a_non_positive_change_floor() -> None:
    with pytest.raises(ValueError, match="change_min_interval_seconds"):
        inventory_reconciliation_due(
            age_seconds=None,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            change_min_interval_seconds=0,
        )


_ACTIVE_STARTED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("markers", "expected"),
    [
        ((), False),
        (({"observed_at": "2026-08-16T11:59:59+00:00"},), False),
        (({"observed_at": "2026-08-16T12:00:01+00:00"},), True),
        (({"observed_at": "2026-08-16T12:00:01Z"},), True),
        (
            (
                {"observed_at": "2026-08-16T10:00:00+00:00"},
                {"observed_at": "2026-08-16T13:00:00+00:00"},
            ),
            True,
        ),
    ],
)
def test_change_markers_are_compared_against_the_active_snapshot(
    markers: tuple[object, ...],
    expected: bool,
) -> None:
    assert has_unreconciled_change(markers, active_started_at=_ACTIVE_STARTED_AT) is expected


def test_any_change_marker_is_unreconciled_without_an_active_snapshot() -> None:
    assert (
        has_unreconciled_change(
            ({"observed_at": "2020-01-01T00:00:00+00:00"},),
            active_started_at=None,
        )
        is True
    )


@pytest.mark.parametrize(
    "marker",
    [
        None,
        "not-a-mapping",
        {},
        {"observed_at": ""},
        {"observed_at": "not-a-timestamp"},
        {"observed_at": "2026-08-16T12:00:01"},
        {"observed_at": 17},
    ],
)
def test_a_malformed_change_marker_is_read_as_an_unresolved_change(marker: object) -> None:
    """Reading a broken change record as \"nothing happened\" would hide drift."""

    assert has_unreconciled_change((marker,), active_started_at=_ACTIVE_STARTED_AT) is True


@pytest.mark.parametrize(
    ("failure_streak", "expected"),
    [(1, 60.0), (2, 120.0), (3, 240.0), (9, 15_360.0), (10, 21_600.0), (99, 21_600.0)],
)
def test_failure_backoff_doubles_and_caps_at_the_routine_interval(
    failure_streak: int,
    expected: float,
) -> None:
    assert (
        failure_retry_delay_seconds(failure_streak=failure_streak, interval_seconds=21_600)
        == expected
    )


def test_failure_backoff_rejects_a_streak_that_earned_nothing() -> None:
    with pytest.raises(ValueError, match="failure_streak"):
        failure_retry_delay_seconds(failure_streak=0, interval_seconds=21_600)


@pytest.mark.parametrize(
    ("failure_streak", "failure_age_seconds", "expected"),
    [
        (1, 59.0, False),
        (1, 60.0, True),
        (2, 119.0, False),
        (2, 120.0, True),
        (1, None, True),
    ],
)
def test_a_failed_attempt_waits_out_its_backoff_before_retrying(
    failure_streak: int,
    failure_age_seconds: float | None,
    expected: bool,
) -> None:
    """A source that keeps failing must not consume the provider budget every tick."""

    assert (
        inventory_reconciliation_due(
            age_seconds=100_000.0,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            failure_streak=failure_streak,
            failure_age_seconds=failure_age_seconds,
        )
        is expected
    )


def test_backoff_outranks_an_elapsed_interval_and_an_observed_change() -> None:
    """Neither a due interval nor a fresh change may bypass the failure backoff."""

    assert (
        inventory_reconciliation_due(
            age_seconds=100_000.0,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            failure_streak=4,
            failure_age_seconds=100.0,
            change_demand=True,
            change_min_interval_seconds=120,
        )
        is False
    )


def test_reconciliation_due_rejects_a_negative_failure_streak() -> None:
    with pytest.raises(ValueError, match="failure_streak"):
        inventory_reconciliation_due(
            age_seconds=None,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            failure_streak=-1,
        )


def test_a_change_recorded_while_the_scan_ran_is_not_read_as_covered() -> None:
    """A scan observes state from its start, so a change during it is unproven."""

    during_the_scan = {"recorded_at": "2026-08-16T12:00:30+00:00"}

    assert has_unreconciled_change((during_the_scan,), active_started_at=_ACTIVE_STARTED_AT) is True


def test_recorded_at_outranks_the_provider_event_clock() -> None:
    """The provider clock cannot be ordered against this database's timestamps."""

    marker = {
        "observed_at": "2026-08-16T11:00:00+00:00",
        "recorded_at": "2026-08-16T12:00:30+00:00",
    }

    assert has_unreconciled_change((marker,), active_started_at=_ACTIVE_STARTED_AT) is True


def test_a_marker_without_recorded_at_falls_back_to_the_provider_clock() -> None:
    """Markers written before recorded_at existed still resolve, not read as absent."""

    legacy_old = {"observed_at": "2026-08-16T11:00:00+00:00"}
    legacy_new = {"observed_at": "2026-08-16T13:00:00+00:00"}

    assert has_unreconciled_change((legacy_old,), active_started_at=_ACTIVE_STARTED_AT) is False
    assert has_unreconciled_change((legacy_new,), active_started_at=_ACTIVE_STARTED_AT) is True


def test_a_truncated_marker_set_is_read_as_an_unresolved_change() -> None:
    """A clipped read must not be reported as proof that nothing changed."""

    covered = {"recorded_at": "2026-08-16T11:00:00+00:00"}

    assert has_unreconciled_change((covered,) * 512, active_started_at=_ACTIVE_STARTED_AT) is False
    assert has_unreconciled_change((covered,) * 513, active_started_at=_ACTIVE_STARTED_AT) is True
