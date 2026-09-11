from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.inventory_scheduler import CollectionScheduleAction
from fdai.delivery.inventory_source_policy import (
    CollectionPriorityPolicy,
    CollectionSourceKind,
    SourceCollectionPolicy,
)
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    PostgresInventoryReconciliationGate,
    _pending_resource_count,
    _projection_pending,
    adaptive_reconciliation_decision,
    failure_retry_delay_seconds,
    has_unreconciled_change,
    inventory_reconciliation_due,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
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
    [(119.0, True, False), (120.0, True, True), (21_599.0, True, True), (21_599.0, False, False)],
)
def test_observed_change_makes_a_scan_due_above_the_floor(
    age_seconds: float,
    change_demand: bool,
    expected: bool,
) -> None:
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


_ACTIVE_STARTED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ({"recorded_at": "2026-08-16T11:59:59+00:00"}, False),
        ({"recorded_at": "2026-08-16T12:00:01+00:00"}, True),
        ({"observed_at": "2026-08-16T12:00:01Z"}, True),
        ({"recorded_at": "not-a-timestamp"}, True),
        (None, True),
    ],
)
def test_change_markers_fail_closed_against_snapshot_start(
    marker: object,
    expected: bool,
) -> None:
    assert has_unreconciled_change((marker,), active_started_at=_ACTIVE_STARTED_AT) is expected


def test_recorded_at_outranks_the_provider_event_clock() -> None:
    marker = {
        "observed_at": "2026-08-16T11:00:00+00:00",
        "recorded_at": "2026-08-16T12:00:30+00:00",
    }
    assert has_unreconciled_change((marker,), active_started_at=_ACTIVE_STARTED_AT) is True


def test_truncated_marker_set_is_an_unresolved_change() -> None:
    covered = {"recorded_at": "2026-08-16T11:00:00+00:00"}
    assert has_unreconciled_change((covered,) * 512, active_started_at=_ACTIVE_STARTED_AT) is False
    assert has_unreconciled_change((covered,) * 513, active_started_at=_ACTIVE_STARTED_AT) is True


@pytest.mark.parametrize(
    ("failure_streak", "expected"),
    [(1, 60.0), (2, 120.0), (3, 240.0), (10, 21_600.0), (99, 21_600.0)],
)
def test_failure_backoff_doubles_and_caps_at_the_routine_interval(
    failure_streak: int,
    expected: float,
) -> None:
    assert (
        failure_retry_delay_seconds(
            failure_streak=failure_streak,
            interval_seconds=21_600,
        )
        == expected
    )


def test_failure_backoff_outranks_interval_and_change_demand() -> None:
    assert (
        inventory_reconciliation_due(
            age_seconds=100_000.0,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            failure_streak=4,
            failure_age_seconds=100.0,
            change_demand=True,
        )
        is False
    )


def test_operator_request_is_immediate_but_does_not_bypass_failure_backoff() -> None:
    assert (
        inventory_reconciliation_due(
            age_seconds=1.0,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            operator_requested=True,
        )
        is True
    )
    assert (
        inventory_reconciliation_due(
            age_seconds=100_000.0,
            in_progress=False,
            abandoned_attempt=False,
            interval_seconds=21_600,
            failure_streak=1,
            failure_age_seconds=1.0,
            operator_requested=True,
        )
        is False
    )


def _adaptive_policy() -> SourceCollectionPolicy:
    return SourceCollectionPolicy(
        source_id="arg-snapshot",
        source_kind=CollectionSourceKind.SNAPSHOT,
        target_freshness_seconds=120,
        max_staleness_seconds=600,
        min_poll_interval_seconds=10,
        max_poll_interval_seconds=120,
        budget_window_seconds=60,
        max_requests_per_window=10,
        max_bytes_per_window=1024,
        global_concurrency_limit=2,
        scope_concurrency_limit=1,
        resource_type_concurrency_limit=1,
        endpoint_concurrency_limit=1,
        max_cursor_pages=1,
        max_objects=1,
        max_relationships=1,
        max_run_seconds=60,
        no_progress_timeout_seconds=30,
        jitter_ratio=0.0,
        backoff_base_seconds=5,
        backoff_max_seconds=60,
        circuit_failure_threshold=3,
        circuit_probe_interval_seconds=30,
        priority=CollectionPriorityPolicy(
            base=1,
            changed_boost=2,
            stale_boost=3,
            critical_boost=4,
            operator_requested_boost=5,
        ),
    )


@pytest.mark.parametrize(
    ("failure_code", "abandoned", "failure_streak", "expected_reason"),
    [
        ("throttled", False, 1, "throttled"),
        ("source_unavailable", False, 1, "timeout"),
        (None, True, 1, "no_progress"),
        ("throttled", False, 3, "circuit_open"),
    ],
)
def test_adaptive_gate_maps_durable_failure_pressure(
    failure_code: str | None,
    abandoned: bool,
    failure_streak: int,
    expected_reason: str,
) -> None:
    decision = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=600,
        in_progress=False,
        failure_streak=failure_streak,
        failure_age_seconds=0,
        failure_code=failure_code,
        abandoned_attempt=abandoned,
        change_demand=True,
    )

    assert decision.action is CollectionScheduleAction.WAIT
    assert decision.reason_codes == (expected_reason,)


def test_adaptive_gate_preserves_operator_request_without_bypassing_in_progress() -> None:
    requested = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=1,
        in_progress=False,
        failure_streak=0,
        failure_age_seconds=None,
        failure_code=None,
        abandoned_attempt=False,
        change_demand=False,
        operator_requested=True,
    )
    in_progress = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=1,
        in_progress=True,
        failure_streak=0,
        failure_age_seconds=None,
        failure_code=None,
        abandoned_attempt=False,
        change_demand=False,
        operator_requested=True,
    )

    assert requested.action is CollectionScheduleAction.COLLECT
    assert requested.reason_codes == ("operator_requested",)
    assert in_progress.action is CollectionScheduleAction.WAIT
    assert in_progress.reason_codes == ("in_progress",)


def test_adaptive_gate_collects_stale_snapshot_without_failure_timestamp() -> None:
    decision = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=601,
        in_progress=False,
        failure_streak=0,
        failure_age_seconds=None,
        failure_code=None,
        abandoned_attempt=False,
        change_demand=True,
    )

    assert decision.action is CollectionScheduleAction.COLLECT
    assert decision.due_in_seconds == 0
    assert decision.reason_codes == ("change_demand", "maximum_staleness")


def test_adaptive_gate_collects_when_realtime_overlay_is_open() -> None:
    decision = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=30,
        in_progress=False,
        failure_streak=0,
        failure_age_seconds=None,
        failure_code=None,
        abandoned_attempt=False,
        change_demand=False,
        overlay_open=True,
    )

    assert decision.action is CollectionScheduleAction.COLLECT
    assert decision.due_in_seconds == 0
    assert decision.reason_codes == ("overlay_open",)


def test_pending_tombstones_open_reconciliation_demand() -> None:
    assert _pending_resource_count(overlay_resource_count=2, pending_tombstone_count=3) == 5

    with pytest.raises(ValueError, match="MUST NOT be negative"):
        _pending_resource_count(overlay_resource_count=0, pending_tombstone_count=-1)


def test_pending_ontology_projection_forces_collection() -> None:
    assert (
        _projection_pending(
            {
                "journal_high_watermark": 5,
                "ontology_projection_watermark": 4,
            }
        )
        is True
    )
    decision = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=30,
        in_progress=False,
        failure_streak=0,
        failure_age_seconds=None,
        failure_code=None,
        abandoned_attempt=False,
        change_demand=False,
        projection_pending=True,
    )

    assert decision.action is CollectionScheduleAction.COLLECT
    assert decision.reason_codes == ("projection_pending",)


def test_reconciliation_gate_tracks_every_enabled_accelerator_cursor() -> None:
    gate = PostgresInventoryReconciliationGate(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://example"),
        cursor_scopes=("sub-1",),
        cursor_prefixes=(
            "arg_resource_change_cursor:",
            "inventory_delta_cursor:",
        ),
    )

    assert gate._cursor_keys == (  # noqa: SLF001 - exact durable-key contract
        "arg_resource_change_cursor:sub-1",
        "inventory_delta_cursor:sub-1",
    )


def test_cursor_lag_beyond_source_freshness_forces_collection() -> None:
    decision = adaptive_reconciliation_decision(
        policy=_adaptive_policy(),
        age_seconds=30,
        in_progress=False,
        failure_streak=0,
        failure_age_seconds=None,
        failure_code=None,
        abandoned_attempt=False,
        change_demand=False,
        cursor_lag_seconds=1,
    )

    assert decision.action is CollectionScheduleAction.COLLECT
    assert decision.reason_codes == ("cursor_lag",)
