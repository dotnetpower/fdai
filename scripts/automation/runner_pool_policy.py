"""Pure capacity recommendations; only one external reconciler may apply authorized changes.

Warm reserves favor immediate scale-out and sustained, idle-only scale-in. Plans
neither authorize mutations nor establish queue-time or throughput SLO results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MAX_RUNNERS = 128
MAX_DURATION_SECONDS = 86_400
RunnerState = Literal["idle", "busy", "starting", "draining"]


def _integer_in_range(name: str, value: int, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")


@dataclass(frozen=True, slots=True)
class PoolPolicy:
    """Validated pool limits; durations are integral seconds, at most one day."""

    pool: str
    warm_idle: int
    maximum: int
    cooldown_seconds: int = 600
    startup_timeout_seconds: int = 300
    stale_after_seconds: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.pool, str) or not self.pool or self.pool.strip() != self.pool:
            raise ValueError("pool must be a nonempty string without surrounding whitespace")
        _integer_in_range("maximum", self.maximum, 1, MAX_RUNNERS)
        _integer_in_range("warm_idle", self.warm_idle, 0, self.maximum)
        _integer_in_range("cooldown_seconds", self.cooldown_seconds, 0, MAX_DURATION_SECONDS)
        _integer_in_range(
            "startup_timeout_seconds", self.startup_timeout_seconds, 1, MAX_DURATION_SECONDS
        )
        _integer_in_range("stale_after_seconds", self.stale_after_seconds, 1, MAX_DURATION_SECONDS)


@dataclass(frozen=True, slots=True)
class RunnerSnapshot:
    """One identity and its current state, unchanged since an aware timestamp."""

    id: str
    state: RunnerState
    since: datetime


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    """Complete, deduplicated capacity, including not-yet-ready and draining slots."""

    observed_at: datetime
    queued_runnable: int
    runners: tuple[RunnerSnapshot, ...]
    low_demand_since: datetime | None = None
    complete: bool = True


@dataclass(frozen=True, slots=True)
class CapacityPlan:
    """Capped target and proposals, not a promise of immediately ready capacity.

    ``unmet_demand`` includes warm-reserve shortfall after proposed starts and
    excludes draining slots. Blocked plans have no actions and unknown counts
    represented by zero; consumers must inspect ``blocked_reason`` first.
    """

    desired_total: int
    start_count: int
    drain_ids: tuple[str, ...]
    blocked_reason: str | None
    unmet_demand: int


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _snapshot_error(policy: PoolPolicy, snapshot: PoolSnapshot, now: datetime) -> str | None:
    if not _aware(now):
        return "invalid_now"
    if type(snapshot.complete) is not bool:
        return "invalid_completeness"
    if not snapshot.complete:
        return "incomplete_snapshot"
    if not _aware(snapshot.observed_at):
        return "invalid_observation_timestamp"
    if snapshot.observed_at > now:
        return "future_snapshot"
    if (now - snapshot.observed_at).total_seconds() > policy.stale_after_seconds:
        return "stale_snapshot"
    if type(snapshot.queued_runnable) is not int or snapshot.queued_runnable < 0:
        return "invalid_queue_count"
    if not isinstance(snapshot.runners, tuple):
        return "invalid_runners"
    if snapshot.low_demand_since is not None:
        if not _aware(snapshot.low_demand_since):
            return "invalid_low_demand_timestamp"
        if snapshot.low_demand_since > snapshot.observed_at:
            return "future_low_demand_timestamp"

    identities: set[str] = set()
    errors: set[str] = set()
    for runner in snapshot.runners:
        if not isinstance(runner, RunnerSnapshot):
            errors.add("invalid_runner")
            continue
        if not isinstance(runner.id, str) or not runner.id or runner.id.strip() != runner.id:
            errors.add("invalid_runner_id")
        elif runner.id in identities:
            errors.add("duplicate_runner_ids")
        else:
            identities.add(runner.id)
        if runner.state not in ("idle", "busy", "starting", "draining"):
            errors.add("invalid_runner_state")
        if not _aware(runner.since):
            errors.add("invalid_runner_timestamp")
        elif runner.since > snapshot.observed_at:
            errors.add("future_runner_timestamp")
        elif (
            runner.state == "starting"
            and (now - runner.since).total_seconds() >= policy.startup_timeout_seconds
        ):
            errors.add("starting_timeout")
    return min(errors) if errors else None


def plan_capacity(policy: PoolPolicy, snapshot: PoolSnapshot, now: datetime) -> CapacityPlan:
    """Plan deterministically from explicit time, without I/O or shared state.

    Every existing slot consumes the hard cap, including draining slots. Busy
    and starting runners are reserved, never cancelled. Snapshot-time evidence
    must prove both cooldowns before removing the longest-idle eligible runners;
    identity breaks ties. A later reconcile must observe each proposed start or
    drain before applying another plan.
    """
    error = _snapshot_error(policy, snapshot, now)
    if error is not None:
        return CapacityPlan(0, 0, (), error, 0)

    busy = sum(runner.state == "busy" for runner in snapshot.runners)
    starting = sum(runner.state == "starting" for runner in snapshot.runners)
    idle = tuple(runner for runner in snapshot.runners if runner.state == "idle")
    active = busy + starting + len(idle)
    demand = busy + snapshot.queued_runnable + policy.warm_idle
    desired = min(policy.maximum, max(demand, busy + starting))
    available_slots = max(0, policy.maximum - len(snapshot.runners))
    starts = min(max(0, desired - active), available_slots)
    unmet = max(0, demand - active - starts)

    low_since = snapshot.low_demand_since
    if (
        low_since is None
        or (snapshot.observed_at - low_since).total_seconds() < policy.cooldown_seconds
    ):
        return CapacityPlan(desired, starts, (), None, unmet)

    eligible = sorted(
        (
            runner
            for runner in idle
            if (snapshot.observed_at - runner.since).total_seconds() >= policy.cooldown_seconds
        ),
        key=lambda runner: (runner.since, runner.id),
    )
    excess = min(max(0, active - demand), max(0, len(idle) - policy.warm_idle))
    drains = tuple(runner.id for runner in eligible[:excess])
    return CapacityPlan(desired, starts, drains, None, unmet)
