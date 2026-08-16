from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    has_unreconciled_change,
    inventory_reconciliation_due,
)


@pytest.mark.parametrize(
    (
        "age_seconds",
        "in_progress",
        "newer_failure",
        "abandoned_attempt",
        "expected",
    ),
    [
        (None, False, False, False, True),
        (1_000.0, False, True, False, True),
        (1_000.0, False, False, True, True),
        (21_599.0, False, False, False, False),
        (21_600.0, False, False, False, True),
        (99_999.0, True, True, True, False),
    ],
)
def test_reconciliation_due_reduces_durable_attempt_state(
    age_seconds: float | None,
    in_progress: bool,
    newer_failure: bool,
    abandoned_attempt: bool,
    expected: bool,
) -> None:
    assert (
        inventory_reconciliation_due(
            age_seconds=age_seconds,
            in_progress=in_progress,
            newer_failure=newer_failure,
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
            newer_failure=False,
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
            newer_failure=False,
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
            newer_failure=False,
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
            newer_failure=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            change_min_interval_seconds=0,
        )


_ACTIVE_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


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
    assert has_unreconciled_change(markers, active_completed_at=_ACTIVE_AT) is expected


def test_any_change_marker_is_unreconciled_without_an_active_snapshot() -> None:
    assert (
        has_unreconciled_change(
            ({"observed_at": "2020-01-01T00:00:00+00:00"},),
            active_completed_at=None,
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

    assert has_unreconciled_change((marker,), active_completed_at=_ACTIVE_AT) is True
