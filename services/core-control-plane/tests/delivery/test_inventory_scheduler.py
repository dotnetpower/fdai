"""Pure transition matrix for adaptive inventory scheduling."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.delivery.inventory_scheduler import (
    CollectionScheduleAction,
    CollectionScheduleState,
    ProviderPressure,
    calculate_collection_schedule,
)
from fdai.delivery.inventory_source_policy import (
    CollectionPriorityPolicy,
    CollectionSourceKind,
    SourceCollectionPolicy,
)


@pytest.fixture
def policy() -> SourceCollectionPolicy:
    return SourceCollectionPolicy(
        source_id="provider-delta",
        source_kind=CollectionSourceKind.DELTA,
        target_freshness_seconds=120,
        max_staleness_seconds=600,
        min_poll_interval_seconds=10,
        max_poll_interval_seconds=480,
        budget_window_seconds=60,
        max_requests_per_window=120,
        max_bytes_per_window=16_777_216,
        global_concurrency_limit=16,
        scope_concurrency_limit=8,
        resource_type_concurrency_limit=4,
        endpoint_concurrency_limit=4,
        max_cursor_pages=100,
        max_objects=10_000,
        max_relationships=20_000,
        max_run_seconds=300,
        no_progress_timeout_seconds=60,
        jitter_ratio=0.0,
        backoff_base_seconds=5,
        backoff_max_seconds=300,
        circuit_failure_threshold=3,
        circuit_probe_interval_seconds=120,
        priority=CollectionPriorityPolicy(
            base=10,
            changed_boost=20,
            stale_boost=30,
            critical_boost=40,
            operator_requested_boost=50,
        ),
    )


@pytest.mark.parametrize(
    ("name", "state", "action", "reason", "due_in"),
    [
        (
            "healthy",
            CollectionScheduleState(30, 30, stable_cycles=1),
            CollectionScheduleAction.WAIT,
            "healthy",
            210.0,
        ),
        (
            "healthy_due",
            CollectionScheduleState(240, 240, stable_cycles=1),
            CollectionScheduleAction.COLLECT,
            "healthy",
            0.0,
        ),
        (
            "lagging",
            CollectionScheduleState(30, 10, cursor_lag_seconds=90),
            CollectionScheduleAction.COLLECT,
            "cursor_lag",
            0.0,
        ),
        (
            "changing",
            CollectionScheduleState(30, 10, change_demand=True),
            CollectionScheduleAction.COLLECT,
            "change_demand",
            0.0,
        ),
        (
            "retry_after",
            CollectionScheduleState(
                300,
                30,
                failure_streak=1,
                provider_pressure=ProviderPressure.THROTTLED,
                retry_after_seconds=90,
            ),
            CollectionScheduleAction.WAIT,
            "provider_retry_after",
            60.0,
        ),
        (
            "timeout",
            CollectionScheduleState(
                300,
                9,
                failure_streak=2,
                provider_pressure=ProviderPressure.TIMEOUT,
            ),
            CollectionScheduleAction.WAIT,
            "timeout",
            1.0,
        ),
        (
            "circuit_open",
            CollectionScheduleState(
                600,
                119,
                failure_streak=3,
                provider_pressure=ProviderPressure.NO_PROGRESS,
            ),
            CollectionScheduleAction.WAIT,
            "circuit_open",
            1.0,
        ),
        (
            "circuit_probe",
            CollectionScheduleState(
                600,
                120,
                provider_pressure=ProviderPressure.CIRCUIT_OPEN,
            ),
            CollectionScheduleAction.PROBE,
            "circuit_open",
            0.0,
        ),
        (
            "recovery",
            CollectionScheduleState(
                600,
                10,
                provider_pressure=ProviderPressure.RECOVERING,
            ),
            CollectionScheduleAction.PROBE,
            "recovery_probe",
            0.0,
        ),
    ],
)
def test_adaptive_schedule_transition_matrix(
    policy: SourceCollectionPolicy,
    name: str,
    state: CollectionScheduleState,
    action: CollectionScheduleAction,
    reason: str,
    due_in: float,
) -> None:
    del name
    decision = calculate_collection_schedule(policy, state)

    assert decision.action is action
    assert decision.reason_codes[0] == reason
    assert decision.due_in_seconds == due_in


def test_quota_pressure_reduces_concurrency_and_exhaustion_waits_for_reset(
    policy: SourceCollectionPolicy,
) -> None:
    pressured = calculate_collection_schedule(
        policy,
        CollectionScheduleState(
            100,
            390,
            provider_pressure=ProviderPressure.QUOTA_PRESSURE,
            budget_remaining_ratio=0.25,
        ),
    )
    exhausted = calculate_collection_schedule(
        policy,
        CollectionScheduleState(
            600,
            20,
            operator_requested=True,
            provider_pressure=ProviderPressure.QUOTA_PRESSURE,
            budget_remaining_ratio=0.0,
            budget_reset_seconds=60,
        ),
    )

    assert pressured.action is CollectionScheduleAction.COLLECT
    assert pressured.concurrency_limit == 1
    assert pressured.reason_codes == ("quota_pressure",)
    assert exhausted.action is CollectionScheduleAction.WAIT
    assert exhausted.due_in_seconds == 40
    assert exhausted.reason_codes == ("quota_exhausted",)

    reset = calculate_collection_schedule(
        policy,
        CollectionScheduleState(
            600,
            60,
            provider_pressure=ProviderPressure.QUOTA_PRESSURE,
            budget_remaining_ratio=0.0,
            budget_reset_seconds=60,
        ),
    )
    assert reset.action is CollectionScheduleAction.PROBE
    assert reset.concurrency_limit == 1


def test_operator_request_never_bypasses_open_circuit(
    policy: SourceCollectionPolicy,
) -> None:
    decision = calculate_collection_schedule(
        policy,
        CollectionScheduleState(
            600,
            10,
            operator_requested=True,
            provider_pressure=ProviderPressure.CIRCUIT_OPEN,
        ),
    )

    assert decision.action is CollectionScheduleAction.WAIT
    assert decision.priority == 90
    assert decision.reason_codes == ("circuit_open",)


def test_successful_recovery_returns_to_healthy_adaptation(
    policy: SourceCollectionPolicy,
) -> None:
    recovering = CollectionScheduleState(
        600,
        120,
        failure_streak=3,
        provider_pressure=ProviderPressure.CIRCUIT_OPEN,
    )
    probe = calculate_collection_schedule(policy, recovering)
    healthy = calculate_collection_schedule(
        policy,
        replace(
            recovering,
            evidence_age_seconds=0,
            last_attempt_age_seconds=0,
            failure_streak=0,
            provider_pressure=ProviderPressure.HEALTHY,
            stable_cycles=0,
        ),
    )

    assert probe.action is CollectionScheduleAction.PROBE
    assert healthy.action is CollectionScheduleAction.WAIT
    assert healthy.interval_seconds == 120
    assert healthy.freshness_available is True


def test_missing_generation_is_due_immediately() -> None:
    policy = SourceCollectionPolicy(
        source_id="provider-snapshot",
        source_kind=CollectionSourceKind.SNAPSHOT,
        target_freshness_seconds=120,
        max_staleness_seconds=600,
        min_poll_interval_seconds=10,
        max_poll_interval_seconds=120,
        budget_window_seconds=60,
        max_requests_per_window=10,
        max_bytes_per_window=1024,
        global_concurrency_limit=1,
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
            changed_boost=1,
            stale_boost=1,
            critical_boost=1,
            operator_requested_boost=1,
        ),
    )

    decision = calculate_collection_schedule(
        policy,
        CollectionScheduleState(None, None),
    )

    assert decision.action is CollectionScheduleAction.COLLECT
    assert decision.reason_codes == ("freshness_unknown",)
