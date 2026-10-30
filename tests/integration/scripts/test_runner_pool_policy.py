"""Deterministic policy invariants, not live queue-time or throughput benchmarks."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from itertools import product
from typing import Any

import pytest
from scripts.automation.runner_pool_policy import (
    MAX_DURATION_SECONDS,
    MAX_RUNNERS,
    CapacityPlan,
    PoolPolicy,
    PoolSnapshot,
    RunnerSnapshot,
    RunnerState,
    plan_capacity,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
POLICY = PoolPolicy("test-pool", warm_idle=4, maximum=32)


def _runner(identity: str, state: RunnerState = "idle", age: int = 900) -> RunnerSnapshot:
    return RunnerSnapshot(identity, state, NOW - timedelta(seconds=age))


def _snapshot(
    queued: int = 0,
    runners: tuple[RunnerSnapshot, ...] = (),
    low_age: int | None = None,
) -> PoolSnapshot:
    low_since = None if low_age is None else NOW - timedelta(seconds=low_age)
    return PoolSnapshot(NOW, queued, runners, low_since)


@pytest.mark.parametrize("queued", [0, 8, 16, 32, 64])
def test_bursts_start_immediately_and_respect_exact_cap(queued: int) -> None:
    runners = tuple(_runner(f"idle-{index}") for index in range(4))
    plan = plan_capacity(POLICY, _snapshot(queued, runners), NOW)
    target = min(queued + 4, 32)
    assert plan == CapacityPlan(target, target - 4, (), None, max(0, queued + 4 - 32))
    assert len(runners) + plan.start_count <= POLICY.maximum


@pytest.mark.parametrize("maximum", [4, 8, 32, MAX_RUNNERS])
@pytest.mark.parametrize("queued", [0, 8, 16, 32, 64])
def test_mixed_state_safety_invariants(maximum: int, queued: int) -> None:
    states: tuple[RunnerState, ...] = ("busy", "idle", "starting", "draining")
    for warm, counts in product((0, 2), product(range(3), repeat=4)):
        if sum(counts) > maximum:
            continue
        policy = replace(POLICY, warm_idle=warm, maximum=maximum)
        runners = tuple(
            _runner(f"{state}-{index}", state, 10 if state == "starting" else 900)
            for state, count in zip(states, counts, strict=True)
            for index in range(count)
        )
        plan = plan_capacity(policy, _snapshot(queued, runners, 900), NOW)
        busy, idle, starting, draining = counts
        active = busy + idle + starting
        demand = busy + queued + warm
        assert plan.blocked_reason is None
        assert active + draining + plan.start_count <= maximum
        assert 0 <= plan.desired_total <= maximum
        assert not (plan.start_count and plan.drain_ids)
        assert len(plan.drain_ids) <= max(0, idle - warm)
        assert set(plan.drain_ids) <= {runner.id for runner in runners if runner.state == "idle"}
        assert active - len(plan.drain_ids) >= min(active, demand)
        assert plan.unmet_demand == max(0, demand - active - plan.start_count)


def test_empty_pool_prewarms_without_waiting_for_low_demand_history() -> None:
    assert plan_capacity(POLICY, _snapshot(), NOW) == CapacityPlan(4, 4, (), None, 0)


def test_inflight_slots_count_once_and_busy_capacity_is_reserved() -> None:
    runners = (
        _runner("busy-1", "busy"),
        _runner("busy-2", "busy"),
        _runner("idle"),
        _runner("starting-1", "starting", 20),
        _runner("starting-2", "starting", 20),
        _runner("starting-3", "starting", 20),
    )
    plan = plan_capacity(POLICY, _snapshot(8, runners), NOW)
    assert plan == CapacityPlan(14, 8, (), None, 0)


def test_a_reconcile_observing_provisioning_does_not_repeat_starts() -> None:
    initial = _snapshot(8, tuple(_runner(f"warm-{index}") for index in range(4)))
    first = plan_capacity(POLICY, initial, NOW)
    observed = replace(
        initial,
        runners=initial.runners
        + tuple(_runner(f"new-{index}", "starting", 0) for index in range(first.start_count)),
    )
    assert first.start_count == 8
    assert plan_capacity(POLICY, observed, NOW) == CapacityPlan(12, 0, (), None, 0)


@pytest.mark.parametrize("draining", [1, 4, 8])
def test_draining_slots_consume_cap_but_not_ready_capacity(draining: int) -> None:
    policy = replace(POLICY, maximum=8)
    runners = tuple(_runner(f"drain-{index}", "draining") for index in range(draining))
    plan = plan_capacity(policy, _snapshot(8, runners), NOW)
    assert plan == CapacityPlan(8, 8 - draining, (), None, 4 + draining)
    assert len(runners) + plan.start_count == policy.maximum


def test_existing_drains_are_not_counted_as_replacements() -> None:
    policy = replace(POLICY, maximum=8)
    runners = tuple(_runner(f"warm-{index}") for index in range(4)) + (
        _runner("draining", "draining"),
    )
    assert plan_capacity(policy, _snapshot(1, runners), NOW) == CapacityPlan(5, 1, (), None, 0)


def test_replacement_waits_for_confirmed_draining_departure() -> None:
    policy = replace(POLICY, warm_idle=2, maximum=4)
    snapshot = _snapshot(
        2,
        (_runner("idle-1"), _runner("idle-2"), _runner("draining", "draining")),
    )
    assert plan_capacity(policy, snapshot, NOW) == CapacityPlan(4, 1, (), None, 1)
    departed = replace(snapshot, runners=snapshot.runners[:-1])
    assert plan_capacity(policy, departed, NOW) == CapacityPlan(4, 2, (), None, 0)


@pytest.mark.parametrize("low_age", [None, 0, 599])
def test_low_demand_must_be_sustained_before_scale_in(low_age: int | None) -> None:
    runners = tuple(_runner(f"idle-{index}") for index in range(8))
    assert plan_capacity(POLICY, _snapshot(0, runners, low_age), NOW).drain_ids == ()


def test_scale_in_uses_oldest_idle_then_identity_and_keeps_warm_reserve() -> None:
    runners = (
        _runner("idle-b", age=800),
        _runner("idle-a", age=800),
        _runner("oldest", age=1000),
        *(_runner(f"recent-{index}", age=50) for index in range(5)),
    )
    plan = plan_capacity(POLICY, _snapshot(0, runners, 600), NOW)
    assert plan == CapacityPlan(4, 0, ("oldest", "idle-a", "idle-b"), None, 0)


def test_idle_cooldown_has_exact_inclusive_boundary() -> None:
    policy = replace(POLICY, warm_idle=0)
    runners = (_runner("young", age=599), _runner("eligible", age=600))
    assert plan_capacity(policy, _snapshot(0, runners, 600), NOW).drain_ids == ("eligible",)


def test_snapshot_must_prove_cooldown_not_just_time_of_reconcile() -> None:
    snapshot = replace(
        _snapshot(0, tuple(_runner(f"idle-{index}") for index in range(8)), 600),
        observed_at=NOW - timedelta(seconds=1),
    )
    assert plan_capacity(POLICY, snapshot, NOW).drain_ids == ()


def test_queue_resurgence_reserves_slots_despite_old_low_demand_history() -> None:
    runners = tuple(_runner(f"idle-{index}") for index in range(12))
    assert plan_capacity(POLICY, _snapshot(8, runners, 900), NOW).drain_ids == ()
    plan = plan_capacity(POLICY, _snapshot(4, runners, 900), NOW)
    assert len(plan.drain_ids) == 4
    assert len(runners) - len(plan.drain_ids) == 4 + POLICY.warm_idle


def test_busy_starting_and_draining_runners_are_never_cancelled() -> None:
    runners = (
        _runner("busy", "busy"),
        _runner("starting", "starting", 10),
        _runner("draining", "draining"),
        *(_runner(f"idle-{index}") for index in range(8)),
    )
    plan = plan_capacity(POLICY, _snapshot(0, runners, 900), NOW)
    assert len(plan.drain_ids) == 4
    assert all(identity.startswith("idle-") for identity in plan.drain_ids)
    assert plan.start_count == 0


def test_starting_surplus_does_not_remove_existing_warm_idle_runners() -> None:
    runners = tuple(_runner(f"idle-{index}") for index in range(4)) + tuple(
        _runner(f"starting-{index}", "starting", 10) for index in range(8)
    )
    assert plan_capacity(POLICY, _snapshot(0, runners, 900), NOW) == CapacityPlan(8, 0, (), None, 0)


def test_starting_surplus_is_not_cancelled_when_warm_reserve_is_zero() -> None:
    policy = replace(POLICY, warm_idle=0)
    runners = (_runner("starting", "starting", 10),)
    assert plan_capacity(policy, _snapshot(0, runners, 900), NOW) == CapacityPlan(1, 0, (), None, 0)


def test_cooldown_can_be_explicitly_zero_but_history_is_still_required() -> None:
    policy = replace(POLICY, warm_idle=0, cooldown_seconds=0)
    runners = (_runner("idle", age=0),)
    assert plan_capacity(policy, _snapshot(0, runners), NOW).drain_ids == ()
    assert plan_capacity(policy, _snapshot(0, runners, 0), NOW).drain_ids == ("idle",)


def test_above_cap_snapshot_does_not_start_or_cancel_busy_work() -> None:
    policy = replace(POLICY, warm_idle=0, maximum=1)
    runners = (_runner("busy-1", "busy"), _runner("busy-2", "busy"), _runner("idle"))
    assert plan_capacity(policy, _snapshot(8, runners, 900), NOW) == CapacityPlan(1, 0, (), None, 7)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"complete": False}, "incomplete_snapshot"),
        ({"complete": 1}, "invalid_completeness"),
        ({"observed_at": NOW - timedelta(seconds=61)}, "stale_snapshot"),
        ({"observed_at": NOW + timedelta(microseconds=1)}, "future_snapshot"),
        ({"observed_at": NOW.replace(tzinfo=None)}, "invalid_observation_timestamp"),
        ({"observed_at": None}, "invalid_observation_timestamp"),
        ({"queued_runnable": -1}, "invalid_queue_count"),
        ({"queued_runnable": True}, "invalid_queue_count"),
        ({"queued_runnable": 1.0}, "invalid_queue_count"),
        ({"queued_runnable": "1"}, "invalid_queue_count"),
        ({"runners": []}, "invalid_runners"),
        ({"runners": ("not-a-runner",)}, "invalid_runner"),
        ({"low_demand_since": NOW.replace(tzinfo=None)}, "invalid_low_demand_timestamp"),
        ({"low_demand_since": NOW + timedelta(microseconds=1)}, "future_low_demand_timestamp"),
    ],
)
def test_invalid_snapshots_fail_closed(changes: dict[str, Any], reason: str) -> None:
    snapshot = replace(_snapshot(64, (_runner("idle"),)), **changes)
    assert plan_capacity(POLICY, snapshot, NOW) == CapacityPlan(0, 0, (), reason, 0)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"id": ""}, "invalid_runner_id"),
        ({"id": " "}, "invalid_runner_id"),
        ({"id": 1}, "invalid_runner_id"),
        ({"state": "unknown"}, "invalid_runner_state"),
        ({"state": []}, "invalid_runner_state"),
        ({"since": NOW.replace(tzinfo=None)}, "invalid_runner_timestamp"),
        ({"since": None}, "invalid_runner_timestamp"),
        ({"since": NOW + timedelta(microseconds=1)}, "future_runner_timestamp"),
    ],
)
def test_invalid_runners_fail_closed(changes: dict[str, Any], reason: str) -> None:
    runner = replace(_runner("idle"), **changes)
    assert plan_capacity(POLICY, _snapshot(64, (runner,)), NOW) == CapacityPlan(0, 0, (), reason, 0)


@pytest.mark.parametrize("state", ["idle", "busy", "starting", "draining"])
def test_duplicate_identity_is_blocked_even_across_states(state: RunnerState) -> None:
    runners = (_runner("duplicate"), _runner("duplicate", state, 10))
    assert plan_capacity(POLICY, _snapshot(8, runners), NOW) == CapacityPlan(
        0, 0, (), "duplicate_runner_ids", 0
    )


@pytest.mark.parametrize("age", [300, 301, 1000])
def test_expired_starting_slots_block_replacement_and_scale_in(age: int) -> None:
    runners = (_runner("starting", "starting", age), _runner("idle"))
    for queued in (0, 64):
        assert plan_capacity(POLICY, _snapshot(queued, runners, 900), NOW) == CapacityPlan(
            0, 0, (), "starting_timeout", 0
        )


def test_unexpired_starting_slot_is_reserved_at_timeout_boundary() -> None:
    runners = (_runner("starting", "starting", 299),)
    assert plan_capacity(POLICY, _snapshot(8, runners), NOW) == CapacityPlan(12, 11, (), None, 0)


def test_staleness_has_exact_boundary_and_accepts_equivalent_timezones() -> None:
    offset = timezone(timedelta(hours=9))
    snapshot = replace(_snapshot(), observed_at=(NOW - timedelta(seconds=60)).astimezone(offset))
    assert plan_capacity(POLICY, snapshot, NOW) == CapacityPlan(4, 4, (), None, 0)


def test_invalid_reconcile_time_blocks_without_naive_aware_comparison() -> None:
    assert plan_capacity(POLICY, _snapshot(), NOW.replace(tzinfo=None)) == CapacityPlan(
        0, 0, (), "invalid_now", 0
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"pool": ""},
        {"pool": " test"},
        {"pool": "test "},
        {"pool": None},
        {"maximum": 0},
        {"maximum": MAX_RUNNERS + 1},
        {"warm_idle": -1},
        {"warm_idle": 33},
        {"cooldown_seconds": -1},
        {"cooldown_seconds": MAX_DURATION_SECONDS + 1},
        {"startup_timeout_seconds": 0},
        {"startup_timeout_seconds": MAX_DURATION_SECONDS + 1},
        {"stale_after_seconds": 0},
        {"stale_after_seconds": MAX_DURATION_SECONDS + 1},
    ],
)
def test_invalid_configuration_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(POLICY, **changes)


@pytest.mark.parametrize(
    "field",
    ["warm_idle", "maximum", "cooldown_seconds", "startup_timeout_seconds", "stale_after_seconds"],
)
@pytest.mark.parametrize("value", [True, False, 1.5, "4", None])
def test_configuration_rejects_booleans_and_non_integers(field: str, value: Any) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        replace(POLICY, **{field: value})


def test_configuration_accepts_exact_lower_and_upper_bounds() -> None:
    minimum = PoolPolicy("minimal", 0, 1, 0, 1, 1)
    maximum = PoolPolicy("maximal", MAX_RUNNERS, MAX_RUNNERS, *([MAX_DURATION_SECONDS] * 3))
    assert minimum.maximum == 1
    assert maximum.warm_idle == MAX_RUNNERS


@pytest.mark.parametrize(
    "value",
    [
        POLICY,
        _runner("runner"),
        _snapshot(),
        CapacityPlan(4, 4, (), None, 0),
    ],
)
def test_policy_snapshots_and_plans_are_immutable(value: Any) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(value, fields(value)[0].name, "changed")


def test_valid_and_invalid_plans_are_stable_across_observation_order() -> None:
    runners = (
        _runner("idle-b"),
        _runner("idle-a"),
        *(_runner(f"other-{index}") for index in range(6)),
    )
    for observed in (runners, (*runners, _runner("invalid", "starting", 301))):
        snapshot = _snapshot(0, observed, 900)
        expected = plan_capacity(POLICY, snapshot, NOW)
        assert plan_capacity(POLICY, snapshot, NOW) == expected
        assert plan_capacity(POLICY, replace(snapshot, runners=observed[::-1]), NOW) == expected
