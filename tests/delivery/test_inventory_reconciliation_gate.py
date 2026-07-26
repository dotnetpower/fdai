from __future__ import annotations

import pytest

from fdai.delivery.persistence.postgres_inventory_snapshot import (
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
